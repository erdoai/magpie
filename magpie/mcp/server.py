"""MCP server exposing magpie tools for AI agents."""

import logging

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from magpie.db.database import Database
from magpie.embeddings.base import EmbeddingProvider
from magpie.mcp.oauth import MagpieOAuthProvider
from magpie.search.fusion import search as fusion_search

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


def _register_tools(server: FastMCP) -> None:
    """Register all MCP tools on the given server instance."""

    @server.tool()
    async def search(
        query: str,
        category: str | None = None,
        tags: list[str] | None = None,
        workspace: str | None = None,
        limit: int = 10,
    ) -> str:
        """Search the knowledge base using semantic similarity and keyword
        matching. Use this to recall information, find past decisions, or
        check if something has been documented.

        Args:
            query: Natural language query — describe what you're looking for.
            category: Filter by PARA category: project, area, resource, archive.
            tags: Filter to entries matching any of these tags.
            workspace: Scope to a workspace (e.g. "devbot", "crow").
            limit: Max results to return (default 10).
        """
        if not _db:
            return "Error: database not initialized"

        results = await fusion_search(
            db=_db,
            query=query,
            embedder=_embedder,
            category=category,
            tags=tags,
            limit=limit,
        )

        if workspace:
            results = [r for r in results if r.get("workspace") == workspace]

        if not results:
            return "No entries found."

        parts = []
        for entry in results:
            score = entry.get("score", "")
            score_str = f" (score: {score})" if score else ""
            ws = f" [{entry.get('workspace')}]" if entry.get("workspace") else ""
            parts.append(
                f"## [{entry['category']}] {entry['title']}{ws}{score_str}\n"
                f"ID: {entry['id']}\n"
                f"Tags: {', '.join(entry.get('tags', []))}\n\n"
                f"{entry['content']}"
            )
        return "\n\n---\n\n".join(parts)

    @server.tool()
    async def write(
        title: str,
        content: str,
        category: str = "resource",
        tags: list[str] | None = None,
        source: str | None = None,
        workspace: str | None = None,
    ) -> str:
        """Save knowledge to the knowledge base. Use this to persist
        learnings, decisions, patterns, or any information worth
        remembering across sessions.

        Args:
            title: Short descriptive title summarizing the knowledge.
            content: Full content (markdown supported). Include context
                and reasoning.
            category: project (active goal), area (ongoing responsibility),
                resource (reference material). Default: resource.
            tags: Tags for filtering (e.g. ["deploy", "railway"]).
            source: Origin (e.g. "claude-code", "manual", "devbot").
            workspace: Scope to a workspace. Omit for org-wide knowledge.
        """
        if not _db:
            return "Error: database not initialized"

        embedding = None
        if _embedder:
            try:
                embedding = await _embedder.embed(f"{title}\n{content}")
            except Exception:
                logger.exception("Failed to generate embedding")

        entry_id = await _db.create_entry(
            title=title,
            content=content,
            category=category,
            tags=tags,
            source=source,
            embedding=embedding,
            workspace=workspace,
        )
        return f"Created entry {entry_id}: {title}"

    @server.tool()
    async def read(id: str) -> str:
        """Read a specific knowledge entry by its ID. Use after searching
        to get the full content of an entry.

        Args:
            id: The entry ID (from search or list results).
        """
        if not _db:
            return "Error: database not initialized"

        entry = await _db.get_entry(id)
        if not entry:
            return f"Entry {id} not found."

        ws = f" [{entry.get('workspace')}]" if entry.get("workspace") else ""
        return (
            f"# [{entry['category']}] {entry['title']}{ws}\n"
            f"ID: {entry['id']}\n"
            f"Tags: {', '.join(entry.get('tags', []))}\n"
            f"Source: {entry.get('source', 'unknown')}\n"
            f"Updated: {entry['updated_at']}\n\n"
            f"{entry['content']}"
        )

    @server.tool()
    async def list_entries(
        category: str | None = None,
        tags: list[str] | None = None,
        workspace: str | None = None,
        limit: int = 20,
    ) -> str:
        """Browse knowledge entries. Returns titles and metadata. Use
        search instead if you have a specific query — this is for
        browsing what's stored.

        Args:
            category: Filter by PARA category: project, area, resource, archive.
            tags: Filter to entries matching any of these tags.
            workspace: Scope to a specific workspace.
            limit: Max results (default 20).
        """
        if not _db:
            return "Error: database not initialized"

        entries = await _db.list_entries(
            category=category, tags=tags, workspace=workspace, limit=limit
        )
        if not entries:
            return "No entries found."

        lines = []
        for entry in entries:
            tags_str = ", ".join(entry.get("tags", []))
            short_id = entry["id"][:8]
            ws = f" [{entry.get('workspace')}]" if entry.get("workspace") else ""
            lines.append(
                f"- **{entry['title']}** [{entry['category']}]{ws}"
                f" ({short_id}…) {tags_str}"
            )
        return "\n".join(lines)

    @server.tool()
    async def archive(id: str) -> str:
        """Archive a knowledge entry — marks it as completed or deprecated.
        Archived entries won't appear in search but are still accessible.

        Args:
            id: The entry ID to archive.
        """
        if not _db:
            return "Error: database not initialized"

        ok = await _db.archive_entry(id)
        if not ok:
            return f"Entry {id} not found."
        return f"Archived entry {id}."
