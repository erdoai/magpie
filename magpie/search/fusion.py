"""Reciprocal Rank Fusion — combines semantic and keyword search results."""

import asyncio
import logging

from magpie.db.database import Database
from magpie.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)

# Standard RRF constant
RRF_K = 60


async def search(
    db: Database,
    query: str,
    embedder: EmbeddingProvider | None = None,
    user_id: str | None = None,
    org_id: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    limit: int = 10,
    semantic: bool = True,
    keyword: bool = True,
) -> list[dict]:
    """Run dual search with Reciprocal Rank Fusion.

    Falls back gracefully:
    - No embedder or semantic=False → keyword only
    - keyword=False → semantic only
    - Both disabled → empty list
    """
    scope = dict(user_id=user_id, org_id=org_id, category=category, tags=tags)
    # Fetch more than needed from each source for better fusion
    fetch_limit = limit * 3

    tasks = []
    task_names = []

    if semantic and embedder:
        tasks.append(_semantic_search(db, embedder, query, scope, fetch_limit))
        task_names.append("semantic")

    if keyword and query.strip():
        tasks.append(db.search_keyword(query, limit=fetch_limit, **scope))
        task_names.append("keyword")

    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect ranked lists, skipping failures
    ranked_lists: list[list[dict]] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("Search method %s failed: %s", task_names[i], result)
            continue
        ranked_lists.append(result)

    if not ranked_lists:
        return []

    # Single source — no fusion needed
    if len(ranked_lists) == 1:
        entries = ranked_lists[0][:limit]
        for entry in entries:
            entry.pop("distance", None)
            entry.pop("rank", None)
        return entries

    # RRF: score = sum(1 / (k + rank)) across all lists
    scores: dict[str, float] = {}
    entry_map: dict[str, dict] = {}

    for ranked_list in ranked_lists:
        for rank, entry in enumerate(ranked_list):
            eid = entry["id"]
            scores[eid] = scores.get(eid, 0) + 1.0 / (RRF_K + rank)
            if eid not in entry_map:
                entry_map[eid] = entry

    # Sort by fused score descending
    sorted_ids = sorted(scores, key=lambda eid: scores[eid], reverse=True)

    entries = []
    for eid in sorted_ids[:limit]:
        entry = entry_map[eid]
        entry.pop("distance", None)
        entry.pop("rank", None)
        entry["score"] = round(scores[eid], 6)
        entries.append(entry)

    return entries


async def _semantic_search(
    db: Database,
    embedder: EmbeddingProvider,
    query: str,
    scope: dict,
    limit: int,
) -> list[dict]:
    embedding = await embedder.embed(query)
    return await db.search_semantic(embedding, limit=limit, **scope)
