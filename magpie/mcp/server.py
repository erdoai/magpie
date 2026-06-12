"""MCP server exposing magpie tools for AI agents."""

import logging

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from magpie.db.database import Database
from magpie.embeddings.base import EmbeddingProvider
from magpie.links import normalize_target, sync_entry_links
from magpie.mcp.oauth import MagpieOAuthProvider
from magpie.search.fusion import search as fusion_search
from magpie.server.context import AuthContext

logger = logging.getLogger(__name__)

# These get set during app startup
_db: Database | None = None
_embedder: EmbeddingProvider | None = None

# Module-level server — created by create_mcp_server()
mcp_server: FastMCP | None = None


def create_mcp_server(
    oauth_issuer_url: str | None = None,
    oauth_provider: MagpieOAuthProvider | None = None,
) -> FastMCP:
    """Create the FastMCP server, optionally with OAuth."""
    kwargs: dict = {
        "name": "magpie",
        "transport_security": TransportSecuritySettings(
            allowed_hosts=[
                "server-production-3634.up.railway.app",
                "magpie.erdo.ai",
                "localhost",
            ],
        ),
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


def init_mcp(db: Database, embedder: EmbeddingProvider | None) -> None:
    global _db, _embedder
    _db = db
    _embedder = embedder


async def _tool_context() -> AuthContext:
    """Resolve the caller's tenant scope from the MCP OAuth token.

    No token (static-key or auth-disabled deployments) → unrestricted
    single-tenant context, preserving pre-OAuth behavior.
    """
    token = get_access_token()
    user_id = getattr(token, "user_id", None) if token else None
    if not user_id or not _db:
        return AuthContext()
    orgs = await _db.list_user_orgs(user_id)
    if orgs:
        return AuthContext(user_id=user_id, org_id=orgs[0]["id"], role=orgs[0].get("role"))
    return AuthContext(user_id=user_id)


def _format_link(link: dict) -> str:
    """One-line summary of an outgoing link edge."""
    if link["target_type"] == "entry":
        return f"- [[{link['link_text']}]] → {link.get('target_title')} (id: {link['target_id']})"
    if link["target_type"] == "url":
        return f"- [[{link['link_text']}]] → {link['target_ref']}"
    if link["target_type"] == "resource":
        return f"- [[{link['link_text']}]] → resource {link['target_ref']}"
    return f"- [[{link['link_text']}]] (unresolved)"


def _register_tools(server: FastMCP) -> None:
    """Register all MCP tools on the given server instance."""

    @server.tool()
    async def search(
        query: str,
        workspace: str | None = None,
        project: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> str:
        """Search the knowledge base. Uses semantic + keyword matching.

        Args:
            query: What you're looking for — natural language.
            workspace: Which app/product namespace to search in (e.g.
                "reach", "alertee", "magpie", "general"). Omit to search all.
            project: Narrower work area within the workspace (e.g. a
                customer or product slug). Omit to search the whole workspace.
            category: Filter by type: project, area, resource, archive.
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
            category=category,
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
                f"Category: {entry['category']} | "
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
        category: str = "resource",
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
            category: project (active goal), area (ongoing
                responsibility), resource (reference). Default: resource.
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
                category=category,
                tags=tags,
                source=source,
                embedding=embedding,
                user_id=ctx.user_id,
                org_id=ctx.org_id,
                workspace=workspace,
                project=project,
            )
            await sync_entry_links(_db, entry_id)
            if was_updated:
                return f"Updated existing entry {entry_id} in [{scope}]: {title}"
            return f"Created entry {entry_id} in [{scope}]: {title}"

        entry_id = await _db.create_entry(
            title=title,
            content=content,
            category=category,
            tags=tags,
            source=source,
            embedding=embedding,
            user_id=ctx.user_id,
            org_id=ctx.org_id,
            workspace=workspace,
            project=project,
        )
        await sync_entry_links(_db, entry_id)
        return f"Created entry {entry_id} in [{scope}]: {title}"

    @server.tool()
    async def read(id: str) -> str:
        """Read a knowledge entry by ID. Use after search/list to
        get full content.

        Args:
            id: The entry ID.
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        entry = await _db.get_entry(id)
        if not entry or not ctx.can_access(entry):
            return f"Entry {id} not found."

        ws = entry.get("workspace") or "general"
        scope = f"{ws}/{entry['project']}" if entry.get("project") else ws
        result = (
            f"# [{scope}] {entry['title']}\n"
            f"Category: {entry['category']} | "
            f"Tags: {', '.join(entry.get('tags', []))}\n"
            f"Source: {entry.get('source', 'unknown')} | "
            f"Updated: {entry['updated_at']}\n"
            f"ID: {entry['id']}\n\n"
            f"{entry['content']}"
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
        return result

    @server.tool()
    async def list_entries(
        workspace: str | None = None,
        project: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> str:
        """Browse knowledge entries. Use search if you have a specific
        query — this is for exploring what's stored.

        Args:
            workspace: Filter to a workspace. Omit to see all.
            project: Filter to a project within the workspace.
            category: Filter by type: project, area, resource, archive.
            tags: Filter to entries matching any of these tags.
            limit: Max results (default 20).
        """
        if not _db:
            return "Error: database not initialized"

        ctx = await _tool_context()
        entries = await _db.list_entries(
            category=category,
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
            lines.append(
                f"- **{entry['title']}** [{scope}/{entry['category']}]"
                f" ({short_id}…) {tags_str}"
            )
        return "\n".join(lines)

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
        entry = await _db.get_entry(id)
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

        entry = await _db.get_entry(id)
        if not entry or not ctx.can_access(entry):
            return f"Entry {id} not found."

        ok = await _db.archive_entry(id)
        if not ok:
            return f"Entry {id} not found."
        return f"Archived entry {id}."

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
        category: str = "resource",
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
            category: PARA category. Default: resource.
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
            entry = await _db.get_entry(source_id)
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
            category=category,
            tags=tags,
            embedding=embedding,
            user_id=ctx.user_id,
            org_id=ctx.org_id,
            workspace=workspace,
            project=project,
        )
        await sync_entry_links(_db, new_id)
        return (
            f"Merged {len(source_ids)} entries into {new_id}: {title}\n"
            f"Archived: {', '.join(source_ids)}"
        )
