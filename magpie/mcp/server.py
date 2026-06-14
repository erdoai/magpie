"""MCP server exposing magpie tools for AI agents."""

import base64
import json
import logging
import mimetypes
from urllib.parse import urlsplit
from uuid import uuid4

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from magpie import activity
from magpie.attachments import (
    attachment_payload,
    handle_for,
    infer_kind,
    is_browser_safe,
    storage_key_for,
)
from magpie.bulk import BulkError, build_changes, build_match, run_bulk
from magpie.db.database import Database
from magpie.embeddings.base import EmbeddingProvider
from magpie.kv import VALUE_TYPES, kv_value_changed, validate_value
from magpie.links import normalize_target, sync_entry_links
from magpie.manifest import normalize_slug
from magpie.mcp.oauth import MagpieOAuthProvider
from magpie.resolve import resolve_entry
from magpie.search.fusion import search as fusion_search
from magpie.server.context import AuthContext, resolve_active_org

logger = logging.getLogger(__name__)

# These get set during app startup
_db: Database | None = None
_embedder: EmbeddingProvider | None = None
_storage = None
_settings = None

# Module-level server — created by create_mcp_server()
mcp_server: FastMCP | None = None


def create_mcp_server(
    oauth_issuer_url: str | None = None,
    oauth_provider: MagpieOAuthProvider | None = None,
    allowed_hosts: list[str] | None = None,
) -> FastMCP:
    """Create the FastMCP server, optionally with OAuth."""
    hosts = ["localhost", "127.0.0.1"]
    if oauth_issuer_url:
        hosts.append(urlsplit(oauth_issuer_url).netloc)
    if allowed_hosts:
        hosts.extend(h for h in allowed_hosts if h)

    kwargs: dict = {
        "name": "magpie",
        "transport_security": TransportSecuritySettings(allowed_hosts=hosts),
    }

    if oauth_issuer_url and oauth_provider:
        kwargs["auth_server_provider"] = oauth_provider
        kwargs["auth"] = AuthSettings(
            issuer_url=oauth_issuer_url,
            resource_server_url=oauth_issuer_url,
            service_documentation_url=None,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["read", "write"],
                default_scopes=["read", "write"],
            ),
            revocation_options=RevocationOptions(enabled=True),
            required_scopes=[],
        )
        logger.info("MCP OAuth enabled (issuer: %s)", oauth_issuer_url)

    server = FastMCP(**kwargs)
    _register_tools(server)
    return server


def init_mcp(
    db: Database,
    embedder: EmbeddingProvider | None,
    storage=None,
    settings=None,
) -> None:
    global _db, _embedder, _storage, _settings
    _db = db
    _embedder = embedder
    _storage = storage
    _settings = settings


async def _tool_context() -> AuthContext:
    """Resolve the caller's tenant scope from the MCP OAuth token.

    No token (static-key or auth-disabled deployments) → unrestricted
    single-tenant context, preserving pre-OAuth behavior.
    """
    token = get_access_token()
    user_id = getattr(token, "user_id", None) if token else None
    if not user_id or not _db:
        # No token: static-key / auth-disabled deployment acts as the system.
        return AuthContext(actor_type="system")
    # No per-request header over MCP — use the saved default org (falling back
    # to first membership), consistent with the REST session path.
    org_id, role = await resolve_active_org(_db, user_id, None)
    return AuthContext(
        user_id=user_id, org_id=org_id, role=role,
        actor_type="user", actor_ref="mcp",
    )


def _format_link(link: dict) -> str:
    """One-line summary of an outgoing link edge."""
    if link["target_type"] == "entry":
        return f"- [[{link['link_text']}]] → {link.get('target_title')} (id: {link['target_id']})"
    if link["target_type"] == "url":
        return f"- [[{link['link_text']}]] → {link['target_ref']}"
    if link["target_type"] == "resource":
        return f"- [[{link['link_text']}]] → resource {link['target_ref']}"
    return f"- [[{link['link_text']}]] (unresolved)"


def _format_attachment_line(att: dict) -> str:
    role = f" role={att['role']}" if att.get("role") else ""
    desc = f" — {att['description']}" if att.get("description") else ""
    return (
        f"- {att['filename']} [{att['kind']}]{role}"
        f" ({att['byte_size']} bytes, handle: {handle_for(att['id'])}){desc}"
    )


def _register_tools(server: FastMCP) -> None:
    """Register all MCP tools on the given server instance."""

    @server.tool()
    async def search(
        query: str,
        workspace: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> str:
        """Search the knowledge base. Uses semantic + keyword matching.
        Archived entries are excluded.

        Args:
            query: What you're looking for — natural language.
            workspace: Which app/product namespace to search in (e.g.
                "reach", "alertee", "magpie", "general"). Omit to search all.
            project: Narrower work area within the workspace (e.g. a
                customer or product slug). Omit to search the whole workspace.
            tags: Filter to entries matching any of these tags.
            limit: Max results (default 10).
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        results = await fusion_search(
            db=_db,
            query=query,
            embedder=_embedder,
            user_id=ctx.user_id,
            org_id=ctx.org_id,
            workspace=workspace,
            project=project,
            tags=tags,
            limit=limit,
        )

        if not results:
            return "No entries found."

        parts = []
        for entry in results:
            score = entry.get("score", "")
            score_str = f" (score: {score})" if score else ""
            ws = entry.get("workspace") or "general"
            scope = f"{ws}/{entry['project']}" if entry.get("project") else ws
            parts.append(
                f"## [{scope}] {entry['title']}{score_str}\n"
                f"Tags: {', '.join(entry.get('tags', []))}\n"
                f"ID: {entry['id']}\n\n"
                f"{entry['content']}"
            )
        return "\n\n---\n\n".join(parts)

    @server.tool()
    async def write(
        title: str,
        content: str,
        workspace: str,
        project: str | None = None,
        tags: list[str] | None = None,
        source: str | None = None,
        dedupe: bool = False,
    ) -> str:
        """Save knowledge. Use this to persist learnings, decisions,
        patterns, or anything worth remembering across sessions.

        Args:
            title: Short descriptive title.
            content: Full content (markdown). Include context and
                reasoning, not just the conclusion.
            workspace: Which app/product namespace this relates to (e.g.
                "reach", "alertee", "magpie", "general"). Required.
            project: Narrower work area within the workspace (e.g. a
                customer or product slug). Optional.
            tags: Tags for filtering (e.g. ["deploy", "railway"]).
            source: Where this came from (e.g. "claude-code", "manual").
            dedupe: If true, update an existing similar entry instead
                of creating a new one when a close match is found.
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        if not ctx.has_role("editor"):
            return "Error: your role does not allow writing knowledge."

        embedding = None
        if _embedder:
            try:
                embedding = await _embedder.embed(f"{title}\n{content}")
            except Exception:
                logger.exception("Failed to generate embedding")

        scope = f"{workspace}/{project}" if project else workspace
        if dedupe:
            entry_id, was_updated = await _db.upsert_entry(
                title=title,
                content=content,
                tags=tags,
                source=source,
                embedding=embedding,
                user_id=ctx.user_id,
                org_id=ctx.org_id,
                workspace=workspace,
                project=project,
                **ctx.actor,
            )
            await sync_entry_links(_db, entry_id)
            entry = await _db.get_entry(entry_id, trusted=True)  # just written above
            if was_updated:
                await activity.entry_updated(_db, ctx, entry, changed=[])
                return f"Updated existing entry {entry_id} in [{scope}]: {title}"
            await activity.entry_created(_db, ctx, entry)
            return f"Created entry {entry_id} in [{scope}]: {title}"

        entry_id = await _db.create_entry(
            title=title,
            content=content,
            tags=tags,
            source=source,
            embedding=embedding,
            user_id=ctx.user_id,
            org_id=ctx.org_id,
            workspace=workspace,
            project=project,
        )
        await sync_entry_links(_db, entry_id)
        entry = await _db.get_entry(entry_id, trusted=True)  # just created above
        await activity.entry_created(_db, ctx, entry)
        return f"Created entry {entry_id} in [{scope}]: {title}"

    @server.tool()
    async def read(id: str, resolved: bool = False) -> str:
        """Read a knowledge entry by ID. Use after search/list to
        get full content.

        Args:
            id: The entry ID.
            resolved: Render {{kv.paths}}, {{attachment:...}},
                and [[wikilinks]] to their current values/links instead
                of returning the raw Markdown.
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        entry = await _db.get_entry(id, **ctx.view_filter)
        if not entry or not ctx.can_access(entry):
            return f"Entry {id} not found."

        content = entry["content"]
        if resolved:
            resolution = await resolve_entry(_db, entry, ctx, _settings)
            content = resolution["markdown"]

        ws = entry.get("workspace") or "general"
        scope = f"{ws}/{entry['project']}" if entry.get("project") else ws
        archived = " | archived" if entry.get("archived_at") else ""
        result = (
            f"# [{scope}] {entry['title']}\n"
            f"Tags: {', '.join(entry.get('tags', []))}{archived}\n"
            f"Source: {entry.get('source', 'unknown')} | "
            f"Updated: {entry['updated_at']}\n"
            f"ID: {entry['id']}\n\n"
            f"{content}"
        )

        outgoing = await _db.get_outgoing_links(id)
        backlinks = await _db.get_backlinks(
            id, normalize_target(entry["title"]),
            user_id=ctx.user_id, org_id=ctx.org_id,
        )
        if outgoing:
            lines = ["\n\n## Links"]
            for link in outgoing:
                lines.append(_format_link(link))
            result += "\n".join(lines)
        if backlinks:
            lines = ["\n\n## Backlinks"]
            for link in backlinks:
                lines.append(
                    f"- {link['source_title']} (id: {link['source_id']})"
                )
            result += "\n".join(lines)

        attachments = await _db.list_attachments(id)
        if attachments:
            lines = ["\n\n## Attachments"]
            for att in attachments:
                lines.append(_format_attachment_line(att))
            result += "\n".join(lines)
        return result

    @server.tool()
    async def entry_history(id: str, limit: int = 20) -> str:
        """Previous versions of an entry, newest first — what it said before each
        meaningful edit (title/content/tags/source changes), with actor and time.
        The current version is what `read` returns. Use to see how knowledge
        evolved or recover an earlier wording.

        Args:
            id: The entry ID.
            limit: Max revisions (default 20, capped at 100).
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        entry = await _db.get_entry(id, **ctx.view_filter)
        if not entry or not ctx.can_access(entry):
            return f"Entry {id} not found."

        revisions = await _db.list_entry_revisions(id, limit=max(1, min(limit, 100)))
        if not revisions:
            return f"No prior revisions for entry {id} (current version is the only one)."

        parts = [f"# History of {entry['title']} ({id})\n"]
        for rev in revisions:
            when = rev["created_at"].isoformat()
            actor = rev.get("actor_type") or "unknown"
            tags = ", ".join(rev.get("previous_tags") or [])
            parts.append(
                f"## {when} (by {actor})\n"
                f"Title: {rev['previous_title']}\n"
                f"Tags: {tags}\n"
                f"Source: {rev.get('previous_source') or 'unknown'}\n\n"
                f"{rev['previous_content']}"
            )
        return "\n\n---\n\n".join(parts)

    @server.tool()
    async def list_entries(
        workspace: str | None = None,
        project: str | None = None,
        archived: bool | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> str:
        """Browse knowledge entries. Use search if you have a specific
        query — this is for exploring what's stored.

        Args:
            workspace: Filter to a workspace. Omit to see all.
            project: Filter to a project within the workspace.
            archived: false (default behaviour None shows all) to hide
                archived, true to show only archived.
            tags: Filter to entries matching any of these tags.
            limit: Max results (default 20).
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        entries = await _db.list_entries(
            archived=archived,
            tags=tags,
            user_id=ctx.user_id,
            org_id=ctx.org_id,
            workspace=workspace,
            project=project,
            limit=limit,
        )
        if not entries:
            return "No entries found."

        lines = []
        for entry in entries:
            tags_str = ", ".join(entry.get("tags", []))
            short_id = entry["id"][:8]
            ws = entry.get("workspace") or "general"
            scope = f"{ws}/{entry['project']}" if entry.get("project") else ws
            flag = " [archived]" if entry.get("archived_at") else ""
            lines.append(
                f"- **{entry['title']}** [{scope}]{flag}"
                f" ({short_id}…) {tags_str}"
            )
        return "\n".join(lines)

    @server.tool()
    async def list_updates(
        workspace: str | None = None,
        project: str | None = None,
        limit: int = 20,
    ) -> str:
        """Recent activity across the store, newest first — what changed, when,
        and by whom. Durable: survives overwrites and deletes, and covers
        entries, KV, attachments, merges, bulk edits, and bundle pushes. Use it
        to catch up on what's happened since you last looked.

        Args:
            workspace: Filter to a workspace. Omit to see all.
            project: Filter to a project within the workspace.
            limit: Max events (default 20, capped at 100).
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        events = await _db.list_activity(
            org_id=ctx.org_id,
            user_id=ctx.user_id,
            workspace=workspace,
            project=project,
            limit=max(1, min(limit, 100)),
            trusted=ctx.is_unrestricted,
        )
        if not events:
            return "No recent activity."

        lines = []
        for e in events:
            scope = e.get("workspace") or "general"
            if e.get("project"):
                scope = f"{scope}/{e['project']}"
            title = e.get("subject_title") or e.get("subject_id") or ""
            actor = e.get("actor_type") or "unknown"
            when = e["created_at"].isoformat()
            lines.append(f"- {when} · {e['action']} {title} [{scope}] (by {actor})")
        return "\n".join(lines)

    @server.tool()
    async def resolve_knowledge(id: str) -> str:
        """Resolve an entry's references and return rendered Markdown plus
        a dependency report. References: {{kv.key.path}} values,
        {{kv:slug/key#path}}, {{attachment:role}}, [[wikilinks]].
        Unresolved references appear as ⟦unresolved: ...⟧ with a reason.

        Args:
            id: The entry ID.
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        entry = await _db.get_entry(id, **ctx.view_filter)
        if not entry or not ctx.can_access(entry):
            return f"Entry {id} not found."

        resolution = await resolve_entry(_db, entry, ctx, _settings)
        parts = [resolution["markdown"]]
        if resolution["dependencies"]:
            lines = ["## Dependencies"]
            for dep in resolution["dependencies"]:
                detail = f" — {dep['detail']}" if dep.get("detail") else ""
                target = f" (id: {dep['target_id']})" if dep.get("target_id") else ""
                lines.append(
                    f"- {dep['ref']} [{dep['kind']}] {dep['status']}{target}{detail}"
                )
            parts.append("\n".join(lines))
        return "\n\n---\n\n".join(parts)

    @server.tool()
    async def list_links(id: str) -> str:
        """List links and backlinks for a knowledge entry.

        Links are parsed from [[wikilinks]] in entry Markdown. Targets can
        be other entries, external URLs, product resources (app:type:id),
        or unresolved titles. Backlinks are entries that reference this one.

        Args:
            id: The entry ID.
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        entry = await _db.get_entry(id, **ctx.view_filter)
        if not entry or not ctx.can_access(entry):
            return f"Entry {id} not found."

        outgoing = await _db.get_outgoing_links(id)
        backlinks = await _db.get_backlinks(
            id, normalize_target(entry["title"]),
            user_id=ctx.user_id, org_id=ctx.org_id,
        )

        if not outgoing and not backlinks:
            return "No links or backlinks."

        parts = []
        if outgoing:
            parts.append("## Links\n" + "\n".join(_format_link(li) for li in outgoing))
        if backlinks:
            parts.append("## Backlinks\n" + "\n".join(
                f"- {li['source_title']} (id: {li['source_id']})" for li in backlinks
            ))
        return "\n\n".join(parts)

    @server.tool()
    async def archive(id: str) -> str:
        """Archive a knowledge entry — marks it as completed/deprecated.
        Won't appear in search results.

        Args:
            id: The entry ID to archive.
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        if not ctx.has_role("editor"):
            return "Error: your role does not allow archiving knowledge."

        entry = await _db.get_entry(id, **ctx.view_filter)
        if not entry or not ctx.can_access(entry):
            return f"Entry {id} not found."

        ok = await _db.archive_entry(id)
        if not ok:
            return f"Entry {id} not found."
        await activity.entry_archived(_db, ctx, entry, archived=True)
        return f"Archived entry {id}."

    @server.tool()
    async def upload_attachment(
        entry_id: str,
        filename: str,
        content_base64: str,
        description: str | None = None,
        role: str | None = None,
        public: bool = False,
    ) -> str:
        """Attach a file to a knowledge entry — logos, screenshots, SQL
        snippets, briefs, reference docs. Future agents reuse these real
        assets instead of recreating or hotlinking them.

        Args:
            entry_id: The entry that owns this attachment.
            filename: Filename with extension (drives kind/media type).
                Use role conventions for brand work: logo-primary,
                favicon-32x32, hero-*, screenshot-*, query-*.
            content_base64: File bytes, base64-encoded.
            description: What this is and when to use it.
            role: Deterministic role tag (e.g. "logo-primary").
            public: Serve via stable /public/assets URL (browser-safe
                images only) — for generated pages that need durable links.
        """
        if not _db:
            return "Error: database not initialized"
        if not _storage:
            return "Error: attachment storage not configured"

        ctx = await _tool_context()
        if not ctx.has_role("editor"):
            return "Error: your role does not allow uploading attachments."

        entry = await _db.get_entry(entry_id, **ctx.view_filter)
        if not entry or not ctx.can_access(entry):
            return f"Entry {entry_id} not found."

        try:
            data = base64.b64decode(content_base64, validate=True)
        except Exception:
            return "Error: content_base64 is not valid base64."
        if not data:
            return "Error: empty file."

        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        kind = infer_kind(filename, media_type)
        if public and not is_browser_safe(media_type):
            return "Error: only browser-safe image media can be public."

        att_id = uuid4().hex
        storage_key = storage_key_for(entry.get("org_id"), entry_id, att_id, filename)
        await _storage.put(storage_key, data, media_type)
        await _db.create_attachment(
            att_id=att_id,
            entry_id=entry_id,
            kind=kind,
            filename=filename,
            media_type=media_type,
            storage_key=storage_key,
            byte_size=len(data),
            org_id=entry.get("org_id"),
            description=description,
            role=role,
            public=public,
            created_by_user_id=ctx.user_id,
        )
        await activity.attachment_added(
            _db, ctx,
            {
                "id": att_id, "filename": filename, "role": role,
                "media_type": media_type, "byte_size": len(data),
            },
            entry,
        )
        return (
            f"Attached {filename} ({kind}, {len(data)} bytes) to entry {entry_id}.\n"
            f"Handle: {handle_for(att_id)}"
        )

    @server.tool()
    async def list_attachments(entry_id: str) -> str:
        """List attachments on a knowledge entry.

        Args:
            entry_id: The entry ID.
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        entry = await _db.get_entry(entry_id, **ctx.view_filter)
        if not entry or not ctx.can_access(entry):
            return f"Entry {entry_id} not found."

        attachments = await _db.list_attachments(entry_id)
        if not attachments:
            return "No attachments."
        return "\n".join(_format_attachment_line(att) for att in attachments)

    @server.tool()
    async def get_attachment(id: str) -> str:
        """Read an attachment by ID (or magpie:<id> handle). Small SQL/text
        attachments return their content inline; binaries return a
        download URL.

        Args:
            id: Attachment ID or magpie:<id> handle.
        """
        if not _db:
            return "Error: database not initialized"

        att_id = id.removeprefix("magpie:")
        ctx = await _tool_context()
        att = await _db.get_attachment(att_id)
        if att:
            entry = await _db.get_entry(att["entry_id"], **ctx.view_filter)
            if not entry or not ctx.can_access(entry):
                att = None
        if not att:
            return f"Attachment {id} not found."

        payload = await attachment_payload(att, _storage, _settings)
        lines = [
            f"# {att['filename']} ({att['kind']}, {att['byte_size']} bytes)",
            f"Handle: {payload['handle']} | Media type: {att['media_type']}",
            f"Entry: {att['entry_id']}",
        ]
        if att.get("role"):
            lines.append(f"Role: {att['role']}")
        if att.get("description"):
            lines.append(f"Description: {att['description']}")
        if payload.get("public_url"):
            lines.append(f"Public URL: {payload['public_url']}")
        if payload.get("content_text") is not None:
            lines.append(f"\n```\n{payload['content_text']}\n```")
        else:
            lines.append(f"Download: {payload['download_url']}")
        return "\n".join(lines)

    @server.tool()
    async def kv_list(
        workspace: str | None = None,
        project: str | None = None,
    ) -> str:
        """List KV stores — named typed key->value stores for structured
        context (strategy, config, brand tokens, advisories, metrics).

        Args:
            workspace: Filter to a workspace. Omit to see all.
            project: Filter to a project within the workspace.
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        stores = await _db.list_kv_stores(
            org_id=ctx.org_id, workspace=workspace, project=project
        )
        stores = [
            s for s in stores
            if ctx.can_access({"user_id": None, "org_id": s.get("org_id")})
        ]
        if not stores:
            return "No KV stores found."

        lines = []
        for store in stores:
            ws = store.get("workspace") or "global"
            scope = f"{ws}/{store['project']}" if store.get("project") else ws
            desc = f" — {store['description']}" if store.get("description") else ""
            lines.append(
                f"- **{store['slug']}** [{scope}]"
                f" ({store['key_count']} keys){desc}"
            )
        return "\n".join(lines)

    @server.tool()
    async def kv_get(
        store: str,
        key: str,
        workspace: str | None = None,
        project: str | None = None,
    ) -> str:
        """Read a value from a KV store by key. Returns the value
        plus its declared value_type so you can deserialize correctly.

        Args:
            store: KV store slug (e.g. "reach.strategy").
            key: Key within the store.
            workspace: Workspace scope for slug lookup.
            project: Project scope for slug lookup.
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        kv = await _db.find_kv_store(
            store, org_id=ctx.org_id, workspace=workspace, project=project
        )
        if not kv or not ctx.can_access({"user_id": None, "org_id": kv.get("org_id")}):
            return f"KV store {store} not found."

        pair = await _db.get_kv_pair(kv["id"], key, **ctx.view_filter)
        if not pair:
            keys = [p["key"] for p in await _db.list_kv_pairs(kv["id"])]
            hint = f" Available keys: {', '.join(keys)}" if keys else ""
            return f"Key {key} not found in {store}.{hint}"

        summary = f"Summary: {pair['summary']}\n" if pair.get("summary") else ""
        return (
            f"# {store}/{key}\n"
            f"Type: {pair['value_type']} | Updated: {pair['updated_at']}\n"
            f"{summary}\n"
            f"{json.dumps(pair['value'], indent=2, default=str)}"
        )

    @server.tool()
    async def kv_history(
        store: str,
        key: str,
        workspace: str | None = None,
        project: str | None = None,
        limit: int = 20,
    ) -> str:
        """Previous values of a KV pair, newest first — what the key held before
        each meaningful set, with actor and time. The current value is what
        `kv_get` returns.

        Args:
            store: KV store slug.
            key: Key within the store.
            workspace: Workspace scope for slug lookup.
            project: Project scope for slug lookup.
            limit: Max revisions (default 20, capped at 100).
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        kv = await _db.find_kv_store(
            store, org_id=ctx.org_id, workspace=workspace, project=project
        )
        if not kv or not ctx.can_access({"user_id": None, "org_id": kv.get("org_id")}):
            return f"KV store {store} not found."

        revisions = await _db.list_kv_revisions(kv["id"], key, limit=max(1, min(limit, 100)))
        if not revisions:
            return f"No prior revisions for {store}/{key}."

        parts = [f"# History of {store}/{key}\n"]
        for rev in revisions:
            when = rev["created_at"].isoformat()
            actor = rev.get("actor_type") or "unknown"
            summary = f"Summary: {rev['previous_summary']}\n" if rev.get("previous_summary") else ""
            parts.append(
                f"## {when} (by {actor})\n"
                f"Type: {rev['previous_value_type']}\n{summary}\n"
                f"{json.dumps(rev['previous_value'], indent=2, default=str)}"
            )
        return "\n\n---\n\n".join(parts)

    @server.tool()
    async def kv_set(
        store: str,
        key: str,
        value: str,
        value_type: str = "json",
        summary: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
        create_store: bool = False,
    ) -> str:
        """Write a value to a KV store. Creates or overwrites by key.

        Args:
            store: KV store slug (e.g. "reach.strategy").
            key: Key within the store.
            value: The value, JSON-encoded (e.g. '{"a": 1}', '"text"',
                '42', 'true', '"2026-06-12T10:00:00Z"').
            value_type: json (default), string, integer, float, boolean,
                or datetime (ISO 8601 string). Validated on write.
            summary: Optional human/agent-readable summary of the value.
            workspace: Workspace scope.
            project: Project scope.
            create_store: Create the KV store if it doesn't exist.
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        if not ctx.has_role("editor"):
            return "Error: your role does not allow writing KV pairs."

        try:
            parsed_value = json.loads(value)
        except json.JSONDecodeError as e:
            return f"Error: value is not valid JSON: {e}"

        if value_type not in VALUE_TYPES:
            return f"Error: unknown value_type. One of: {', '.join(VALUE_TYPES)}"
        error = validate_value(parsed_value, value_type)
        if error:
            return f"Error: {error}"

        kv = await _db.find_kv_store(
            store, org_id=ctx.org_id, workspace=workspace, project=project
        )
        if kv and not ctx.can_access({"user_id": None, "org_id": kv.get("org_id")}):
            kv = None
        if kv and kv.get("source") == "repo":
            return (
                f"KV store {store} is repo-canonical; edit the bundle file"
                f" and run `magpie push` (agent writes are rejected to avoid drift)."
            )
        if not kv:
            if not create_store:
                return (
                    f"KV store {store} not found."
                    f" Pass create_store=true to create it."
                )
            # Anti-drift: don't let a new store shadow an existing near-duplicate
            # (e.g. creating "reach_strategy" when "reach-strategy" exists).
            norm = normalize_slug(store)
            siblings = await _db.list_kv_stores(
                org_id=ctx.org_id, workspace=workspace, project=project
            )
            dup = next(
                (s for s in siblings
                 if s["slug"] != store and normalize_slug(s["slug"]) == norm),
                None,
            )
            if dup:
                return (
                    f"Refusing to create {store!r} — near-duplicate of existing "
                    f"{dup['slug']!r}. Use that slug, or pick a clearly distinct name."
                )
            store_id = await _db.create_kv_store(
                slug=store,
                title=store,
                org_id=ctx.org_id,
                workspace=workspace,
                project=project,
                created_by_user_id=ctx.user_id,
            )
            kv = await _db.get_kv_store(store_id, trusted=True)  # just created above
            await activity.kv_store_created(_db, ctx, kv)

        previous = await _db.get_kv_pair(kv["id"], key, trusted=True)
        if kv_value_changed(previous, parsed_value, value_type, summary):
            await _db.create_kv_revision(
                store_id=kv["id"],
                key=key,
                previous_value=previous["value"],
                previous_value_type=previous["value_type"],
                previous_summary=previous.get("summary"),
                org_id=kv.get("org_id"),
                **ctx.actor,
            )
        await _db.set_kv_pair(
            store_id=kv["id"],
            key=key,
            value=parsed_value,
            value_type=value_type,
            summary=summary,
            org_id=kv.get("org_id"),
            created_by_user_id=ctx.user_id,
        )
        await activity.kv_pair_set(_db, ctx, kv, key, value_type, created=previous is None)
        return f"Set {store}/{key} ({value_type})."

    @server.tool()
    async def kv_delete(
        store: str,
        key: str,
        workspace: str | None = None,
        project: str | None = None,
    ) -> str:
        """Delete a key from a KV store.

        Args:
            store: KV store slug.
            key: Key to delete.
            workspace: Workspace scope.
            project: Project scope.
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        if not ctx.has_role("editor"):
            return "Error: your role does not allow deleting KV pairs."

        kv = await _db.find_kv_store(
            store, org_id=ctx.org_id, workspace=workspace, project=project
        )
        if not kv or not ctx.can_access({"user_id": None, "org_id": kv.get("org_id")}):
            return f"KV store {store} not found."
        if kv.get("source") == "repo":
            return (
                f"KV store {store} is repo-canonical; edit the bundle file"
                f" and run `magpie push` (agent writes are rejected to avoid drift)."
            )

        ok = await _db.delete_kv_pair(kv["id"], key)
        if not ok:
            return f"Key {key} not found in {store}."
        await activity.kv_pair_deleted(_db, ctx, kv, key)
        return f"Deleted {store}/{key}."

    @server.tool()
    async def find_duplicates(
        workspace: str | None = None,
        project: str | None = None,
        threshold: float = 0.12,
        limit: int = 50,
    ) -> str:
        """Find clusters of near-duplicate entries by semantic similarity.
        Returns groups of entries that cover the same topic. Use this to
        identify consolidation opportunities before merging.

        Args:
            workspace: Scope to a workspace. Omit to scan all.
            project: Scope to a project within the workspace.
            threshold: Cosine distance threshold — lower is stricter.
                Default 0.12.
            limit: Max pairs to consider. Default 50.
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        clusters = await _db.find_duplicate_clusters(
            workspace=workspace,
            project=project,
            user_id=ctx.user_id,
            org_id=ctx.org_id,
            threshold=threshold,
            limit=limit,
        )

        if not clusters:
            return "No duplicate clusters found."

        parts = []
        for i, cluster in enumerate(clusters, 1):
            avg_dist = sum(
                e.get("min_distance", 0) for e in cluster
            ) / len(cluster)
            lines = [
                f"## Cluster {i} ({len(cluster)} entries,"
                f" avg distance: {avg_dist:.3f})"
            ]
            for entry in cluster:
                ws = entry.get("workspace") or "general"
                snippet = entry["content"][:120].replace("\n", " ")
                dist = entry.get("min_distance", 0)
                tags_str = ", ".join(entry.get("tags", []))
                lines.append(
                    f"- **{entry['title']}** [{ws}] (id: {entry['id']},"
                    f" dist: {dist:.3f})\n"
                    f"  Tags: {tags_str}\n"
                    f"  {snippet}…"
                )
            parts.append("\n".join(lines))

        return "\n\n".join(parts)

    @server.tool()
    async def merge(
        source_ids: list[str],
        title: str,
        content: str,
        tags: list[str] | None = None,
        workspace: str | None = None,
        project: str | None = None,
    ) -> str:
        """Merge multiple entries into one. The source entries are archived
        with lineage tracking. You provide the merged title and content —
        this tool handles the data operation.

        Args:
            source_ids: Entry IDs to merge (will be archived).
            title: Title for the merged entry.
            content: Synthesized content for the merged entry (markdown).
            tags: Tags for the merged entry.
            workspace: Workspace scope.
            project: Project scope within the workspace.
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        if not ctx.has_role("editor"):
            return "Error: your role does not allow merging knowledge."

        if len(source_ids) < 2:
            return "Error: need at least 2 source entries to merge."

        # Every source entry must be visible to the caller
        for source_id in source_ids:
            entry = await _db.get_entry(source_id, **ctx.view_filter)
            if not entry or not ctx.can_access(entry):
                return f"Entry {source_id} not found."

        embedding = None
        if _embedder:
            try:
                embedding = await _embedder.embed(f"{title}\n{content}")
            except Exception:
                logger.exception("Failed to generate embedding for merge")

        new_id = await _db.merge_entries(
            source_ids=source_ids,
            title=title,
            content=content,
            tags=tags,
            embedding=embedding,
            user_id=ctx.user_id,
            org_id=ctx.org_id,
            workspace=workspace,
            project=project,
        )
        await sync_entry_links(_db, new_id)
        entry = await _db.get_entry(new_id, trusted=True)  # just created above
        await activity.entry_merged(_db, ctx, entry, source_ids)
        return (
            f"Merged {len(source_ids)} entries into {new_id}: {title}\n"
            f"Archived: {', '.join(source_ids)}"
        )

    @server.tool()
    async def bulk_edit(
        match_workspace: str | None = None,
        match_project: str | None = None,
        match_tags: list[str] | None = None,
        match_source: str | None = None,
        set_workspace: str | None = None,
        set_project: str | None = None,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
        rename_tag_from: str | None = None,
        rename_tag_to: str | None = None,
        clear_project: bool = False,
        dry_run: bool = True,
    ) -> str:
        """Rescope or retag many entries at once (bulk reorganize).

        Selects every entry matching the match_* filters and applies the
        set_*/tag changes in a single transaction. In-place — ids, links, and
        embeddings are preserved. ALWAYS preview with dry_run=True first
        (returns how many match and a sample of before→after); applying
        (dry_run=False) requires admin and cannot be undone.

        At least one match_* filter is required (never matches the whole
        store). Tag changes apply in order: rename, then remove, then add.

        Args:
            match_workspace: Only entries in this workspace.
            match_project: Only entries in this project.
            match_tags: Only entries having ANY of these tags.
            match_source: Only entries with this source.
            set_workspace: Move matched entries to this workspace.
            set_project: Move matched entries to this project.
            add_tags: Tags to add to every matched entry.
            remove_tags: Tags to remove from every matched entry.
            rename_tag_from: Tag to rename (with rename_tag_to).
            rename_tag_to: New name for rename_tag_from.
            clear_project: Set project to empty on matched entries (e.g. when
                retiring a project namespace).
            dry_run: Preview without writing (default True). Set False to apply.
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        match = build_match(
            workspace=match_workspace,
            project=match_project,
            tags=match_tags,
            source=match_source,
        )
        changes = build_changes(
            workspace=set_workspace,
            project=set_project,
            add_tags=add_tags,
            remove_tags=remove_tags,
            rename_from=rename_tag_from,
            rename_to=rename_tag_to,
            clear=["project"] if clear_project else None,
        )

        result = await run_bulk(_db, ctx, match=match, changes=changes, dry_run=dry_run)
        if isinstance(result, BulkError):
            return f"Error: {result.message}"

        lines = []
        for s in result["sample"]:
            b, a = s["before"], s["after"]
            scope_b = f"{b['workspace'] or '—'}/{b['project'] or '—'}"
            scope_a = f"{a['workspace'] or '—'}/{a['project'] or '—'}"
            change = f"{scope_b} {b['tags']} → {scope_a} {a['tags']}"
            lines.append(f"  - {s['title']}: {change}")
        preview = "\n".join(lines)

        if result["applied"]:
            head = f"Applied to {result['updated']} entr{'y' if result['updated'] == 1 else 'ies'}."
        else:
            head = (
                f"Dry run: {result['matched']} entr"
                f"{'y' if result['matched'] == 1 else 'ies'} would change. "
                f"Re-run with dry_run=False to apply (requires admin)."
            )
        return f"{head}\n{preview}" if preview else head
