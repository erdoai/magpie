"""MCP server exposing magpie tools for AI agents."""

import logging

from mcp.server.fastmcp import FastMCP

from magpie.db.database import Database
from magpie.embeddings.base import EmbeddingProvider
from magpie.search.fusion import search as fusion_search

logger = logging.getLogger(__name__)

mcp_server = FastMCP("magpie")

# These get set during app startup
_db: Database | None = None
_embedder: EmbeddingProvider | None = None


def init_mcp(db: Database, embedder: EmbeddingProvider | None) -> None:
    global _db, _embedder
    _db = db
    _embedder = embedder


@mcp_server.tool()
async def magpie_search(
    query: str,
    category: str | None = None,
    tags: list[str] | None = None,
    workspace: str | None = None,
    limit: int = 10,
) -> str:
    """Search knowledge entries using semantic + keyword search.

    Args:
        query: The search query text.
        category: Filter by PARA category (project, area, resource, archive).
        tags: Filter by tags (entries matching any tag are included).
        workspace: Filter by workspace (e.g. "devbot", "crow", "shared").
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


@mcp_server.tool()
async def magpie_write(
    title: str,
    content: str,
    category: str = "resource",
    tags: list[str] | None = None,
    source: str | None = None,
    workspace: str | None = None,
) -> str:
    """Create a new knowledge entry.

    Args:
        title: Short descriptive title.
        content: Full content of the knowledge entry (markdown supported).
        category: PARA category — one of: project, area, resource (default: resource).
        tags: Optional list of tags for filtering.
        source: Optional source identifier (e.g. "crow", "devbot", "manual").
        workspace: Optional workspace to scope this entry to.
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


@mcp_server.tool()
async def magpie_read(id: str) -> str:
    """Read a knowledge entry by ID.

    Args:
        id: The entry ID.
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


@mcp_server.tool()
async def magpie_list(
    category: str | None = None,
    tags: list[str] | None = None,
    workspace: str | None = None,
    limit: int = 20,
) -> str:
    """List knowledge entries, optionally filtered.

    Args:
        category: Filter by PARA category (project, area, resource, archive).
        tags: Filter by tags.
        workspace: Filter by workspace.
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


@mcp_server.tool()
async def magpie_archive(id: str) -> str:
    """Archive a knowledge entry (moves to 'archive' category).

    Args:
        id: The entry ID to archive.
    """
    if not _db:
        return "Error: database not initialized"

    ok = await _db.archive_entry(id)
    if not ok:
        return f"Entry {id} not found."
    return f"Archived entry {id}."
