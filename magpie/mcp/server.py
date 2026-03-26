"""MCP server exposing magpie tools for AI agents."""

import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from magpie.db.database import Database
from magpie.embeddings.base import EmbeddingProvider
from magpie.search.fusion import search as fusion_search

logger = logging.getLogger(__name__)

mcp_server = FastMCP(
    "magpie",
    transport_security=TransportSecuritySettings(
        allowed_hosts=[
            "server-production-3634.up.railway.app",
            "magpie.erdo.ai",
            "localhost",
        ],
    ),
)

# These get set during app startup
_db: Database | None = None
_embedder: EmbeddingProvider | None = None


def init_mcp(db: Database, embedder: EmbeddingProvider | None) -> None:
    global _db, _embedder
    _db = db
    _embedder = embedder


@mcp_server.tool()
async def search(
    query: str,
    workspace: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    limit: int = 10,
) -> str:
    """Search the knowledge base. Uses semantic + keyword matching.

    Args:
        query: What you're looking for — natural language.
        workspace: Which project/area to search in (e.g. "devbot",
            "crow", "magpie", "general"). Omit to search all.
        category: Filter by type: project, area, resource, archive.
        tags: Filter to entries matching any of these tags.
        limit: Max results (default 10).
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
        ws = entry.get("workspace") or "general"
        parts.append(
            f"## [{ws}] {entry['title']}{score_str}\n"
            f"Category: {entry['category']} | "
            f"Tags: {', '.join(entry.get('tags', []))}\n"
            f"ID: {entry['id']}\n\n"
            f"{entry['content']}"
        )
    return "\n\n---\n\n".join(parts)


@mcp_server.tool()
async def write(
    title: str,
    content: str,
    workspace: str,
    category: str = "resource",
    tags: list[str] | None = None,
    source: str | None = None,
) -> str:
    """Save knowledge. Use this to persist learnings, decisions,
    patterns, or anything worth remembering across sessions.

    Args:
        title: Short descriptive title.
        content: Full content (markdown). Include context and
            reasoning, not just the conclusion.
        workspace: Which project this relates to (e.g. "devbot",
            "crow", "magpie", "general"). Required.
        category: project (active goal), area (ongoing
            responsibility), resource (reference). Default: resource.
        tags: Tags for filtering (e.g. ["deploy", "railway"]).
        source: Where this came from (e.g. "claude-code", "manual").
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
    return f"Created entry {entry_id} in [{workspace}]: {title}"


@mcp_server.tool()
async def read(id: str) -> str:
    """Read a knowledge entry by ID. Use after search/list to get
    full content.

    Args:
        id: The entry ID.
    """
    if not _db:
        return "Error: database not initialized"

    entry = await _db.get_entry(id)
    if not entry:
        return f"Entry {id} not found."

    ws = entry.get("workspace") or "general"
    return (
        f"# [{ws}] {entry['title']}\n"
        f"Category: {entry['category']} | "
        f"Tags: {', '.join(entry.get('tags', []))}\n"
        f"Source: {entry.get('source', 'unknown')} | "
        f"Updated: {entry['updated_at']}\n"
        f"ID: {entry['id']}\n\n"
        f"{entry['content']}"
    )


@mcp_server.tool()
async def list_entries(
    workspace: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    limit: int = 20,
) -> str:
    """Browse knowledge entries. Use search if you have a specific
    query — this is for exploring what's stored.

    Args:
        workspace: Filter to a workspace. Omit to see all.
        category: Filter by type: project, area, resource, archive.
        tags: Filter to entries matching any of these tags.
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
        ws = entry.get("workspace") or "general"
        lines.append(
            f"- **{entry['title']}** [{ws}/{entry['category']}]"
            f" ({short_id}…) {tags_str}"
        )
    return "\n".join(lines)


@mcp_server.tool()
async def archive(id: str) -> str:
    """Archive a knowledge entry — marks it as completed/deprecated.
    Won't appear in search results.

    Args:
        id: The entry ID to archive.
    """
    if not _db:
        return "Error: database not initialized"

    ok = await _db.archive_entry(id)
    if not ok:
        return f"Entry {id} not found."
    return f"Archived entry {id}."
