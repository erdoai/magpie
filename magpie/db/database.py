import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg

from magpie.db.migrate import run_migrations

logger = logging.getLogger(__name__)


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Encode/decode JSONB as Python values rather than strings."""
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


def apply_bulk_changes(entry: dict, changes: dict) -> dict:
    """Pure transform: return ``entry`` with a bulk ``changes`` spec applied.

    The single source of truth for bulk semantics — used both to preview a
    dry-run (compute the "after" for sampled rows) and to apply the change
    row by row. Order is fixed and meaningful: scope set, then clear, then
    tag rename → remove → add, then order-preserving dedupe. ``clear`` wins
    over a same-field set.
    """
    new = dict(entry)
    if "workspace" in changes:
        new["workspace"] = changes["workspace"]
    if "project" in changes:
        new["project"] = changes["project"]
    for field in changes.get("clear", []):
        new[field] = None

    tags = list(entry.get("tags") or [])
    rename_from, rename_to = changes.get("rename_from"), changes.get("rename_to")
    if rename_from and rename_to:
        tags = [rename_to if t == rename_from else t for t in tags]
    remove = set(changes.get("remove_tags") or [])
    if remove:
        tags = [t for t in tags if t not in remove]
    for t in changes.get("add_tags") or []:
        tags.append(t)

    seen, deduped = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    new["tags"] = deduped
    return new


class Database:
    def __init__(self, pool: asyncpg.Pool, has_vectors: bool = False):
        self._pool = pool
        self.has_vectors = has_vectors

    @classmethod
    async def connect(cls, database_url: str) -> "Database":
        pool = await asyncpg.create_pool(database_url, init=_init_connection)
        db = cls(pool)
        await run_migrations(pool)

        # Detect pgvector support
        row = await pool.fetchrow(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns"
            " WHERE table_name='entries' AND column_name='embedding') AS has_embedding"
        )
        db.has_vectors = row["has_embedding"] if row else False
        if db.has_vectors:
            logger.info("pgvector detected — semantic search enabled")
        else:
            logger.info("No pgvector — keyword search only")

        logger.info("Database connected and migrations applied")
        return db

    async def close(self) -> None:
        await self._pool.close()

    # -- Entries CRUD --

    async def create_entry(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
        source: str | None = None,
        embedding: list[float] | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
    ) -> str:
        entry_id = uuid4().hex
        now = datetime.now(UTC)
        if embedding and self.has_vectors:
            await self._pool.execute(
                """INSERT INTO entries
                   (id, title, content, tags, source,
                    embedding, user_id, org_id, workspace, project,
                    created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                entry_id,
                title,
                content,
                tags or [],
                source,
                str(embedding),
                user_id,
                org_id,
                workspace,
                project,
                now,
                now,
            )
        else:
            await self._pool.execute(
                """INSERT INTO entries
                   (id, title, content, tags, source,
                    user_id, org_id, workspace, project,
                    created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
                entry_id,
                title,
                content,
                tags or [],
                source,
                user_id,
                org_id,
                workspace,
                project,
                now,
                now,
            )
        return entry_id

    async def get_entry(
        self,
        entry_id: str,
        *,
        user_id: str | None = None,
        org_id: str | None = None,
        trusted: bool = False,
    ) -> dict | None:
        """Fetch an entry by id, enforcing visibility unless ``trusted``.

        Fail-closed: callers pass the viewer's scope (user_id/org_id) or
        ``trusted=True`` for server-internal reads. With neither, only global
        (untenanted) entries are returned. A NULL user_id/org_id never matches
        a tenanted row, so cross-tenant reads return None rather than leaking.
        """
        cols = (
            "id, title, content, tags, source, user_id, org_id,"
            " workspace, project, archived_at, created_at, updated_at"
        )
        if trusted:
            row = await self._pool.fetchrow(
                f"SELECT {cols} FROM entries WHERE id = $1", entry_id
            )
        else:
            row = await self._pool.fetchrow(
                f"SELECT {cols} FROM entries WHERE id = $1"
                " AND ((user_id IS NULL AND org_id IS NULL)"
                " OR user_id = $2 OR org_id = $3)",
                entry_id, user_id, org_id,
            )
        return dict(row) if row else None

    async def update_entry(self, entry_id: str, **fields) -> bool:
        allowed = {"title", "content", "tags", "source", "workspace", "project"}
        if self.has_vectors:
            allowed.add("embedding")
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return False

        # Convert embedding to string for pgvector
        if "embedding" in updates:
            updates["embedding"] = str(updates["embedding"])

        updates["updated_at"] = datetime.now(UTC)

        set_parts = []
        params: list = []
        for i, (col, val) in enumerate(updates.items(), 1):
            set_parts.append(f"{col} = ${i}")
            params.append(val)

        params.append(entry_id)
        sql = f"UPDATE entries SET {', '.join(set_parts)} WHERE id = ${len(params)}"
        result = await self._pool.execute(sql, *params)
        return result == "UPDATE 1"

    async def bulk_update_entries(
        self,
        *,
        match: dict,
        changes: dict,
        user_id: str | None = None,
        org_id: str | None = None,
        trusted: bool = False,
        dry_run: bool = True,
        sample_size: int = 10,
    ) -> dict:
        """Rescope/retag every entry matching ``match`` in one transaction.

        In-place UPDATE — ids, links, and embeddings are preserved (scope/tag
        edits touch neither title nor content, so no re-embed; the FTS trigger
        refreshes the search vector). ``dry_run`` selects and previews without
        writing. Visibility is fail-closed: a tenant caller only ever touches
        their own + active-org rows, never global (NULL/NULL) rows. ``match``
        must be non-empty — refuse to select the whole store.

        Returns ``{matched, updated, applied, sample}`` where each sample item
        is ``{id, title, before, after}`` with scope/tags before and after.
        """
        conditions: list[str] = []
        params: list = []

        if match.get("workspace") is not None:
            params.append(match["workspace"])
            conditions.append(f"workspace = ${len(params)}")
        if match.get("project") is not None:
            params.append(match["project"])
            conditions.append(f"project = ${len(params)}")
        if match.get("source") is not None:
            params.append(match["source"])
            conditions.append(f"source = ${len(params)}")
        if match.get("tags"):
            params.append(match["tags"])
            conditions.append(f"tags && ${len(params)}")

        if not conditions:
            raise ValueError("bulk update requires at least one match filter")

        # Write-visibility: own + active-org rows only. Global (NULL/NULL)
        # rows are never touched by a tenant bulk op. trusted = static key.
        if not trusted:
            if user_id and org_id:
                params.append(user_id)
                uid = len(params)
                params.append(org_id)
                oid = len(params)
                conditions.append(f"(user_id = ${uid} OR org_id = ${oid})")
            elif user_id:
                params.append(user_id)
                conditions.append(f"user_id = ${len(params)}")
            elif org_id:
                params.append(org_id)
                conditions.append(f"org_id = ${len(params)}")
            else:
                # No identity and not trusted ⇒ nothing is writable.
                return {"matched": 0, "updated": 0, "applied": False, "sample": []}

        where = " AND ".join(conditions)
        rows = await self._pool.fetch(
            "SELECT id, title, workspace, project, tags FROM entries"
            f" WHERE {where} ORDER BY updated_at DESC",
            *params,
        )
        matched = [dict(r) for r in rows]

        def _view(e: dict) -> dict:
            return {
                "workspace": e.get("workspace"),
                "project": e.get("project"),
                "tags": list(e.get("tags") or []),
            }

        sample = [
            {
                "id": r["id"],
                "title": r["title"],
                "before": _view(r),
                "after": _view(apply_bulk_changes(r, changes)),
            }
            for r in matched[:sample_size]
        ]

        if dry_run:
            return {
                "matched": len(matched),
                "updated": 0,
                "applied": False,
                "sample": sample,
            }

        now = datetime.now(UTC)
        updated = 0
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for r in matched:
                    after = apply_bulk_changes(r, changes)
                    await conn.execute(
                        "UPDATE entries SET workspace = $1, project = $2,"
                        " tags = $3, updated_at = $4 WHERE id = $5",
                        after["workspace"],
                        after["project"],
                        after["tags"],
                        now,
                        r["id"],
                    )
                    updated += 1

        return {
            "matched": len(matched),
            "updated": updated,
            "applied": True,
            "sample": sample,
        }

    async def delete_entry(self, entry_id: str) -> bool:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Drop outgoing links; demote inbound links to unresolved so
                # other entries' references stay visible (and re-resolvable).
                await conn.execute(
                    "DELETE FROM links WHERE source_type = 'entry' AND source_id = $1",
                    entry_id,
                )
                await conn.execute(
                    "UPDATE links SET target_type = 'unresolved', target_id = NULL"
                    " WHERE target_type = 'entry' AND target_id = $1",
                    entry_id,
                )
                result = await conn.execute(
                    "DELETE FROM entries WHERE id = $1", entry_id
                )
        return result == "DELETE 1"

    async def archive_entry(self, entry_id: str) -> bool:
        result = await self._pool.execute(
            "UPDATE entries SET archived_at = $1, updated_at = $1 WHERE id = $2",
            datetime.now(UTC),
            entry_id,
        )
        return result == "UPDATE 1"

    async def unarchive_entry(self, entry_id: str) -> bool:
        result = await self._pool.execute(
            "UPDATE entries SET archived_at = NULL, updated_at = $1 WHERE id = $2",
            datetime.now(UTC),
            entry_id,
        )
        return result == "UPDATE 1"

    async def list_entries(
        self,
        archived: bool | None = None,
        tags: list[str] | None = None,
        source: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        conditions = []
        params: list = []
        idx = 0

        # archived: None = all, False = active only, True = archived only
        if archived is True:
            conditions.append("archived_at IS NOT NULL")
        elif archived is False:
            conditions.append("archived_at IS NULL")

        if tags:
            idx += 1
            conditions.append(f"tags && ${idx}")
            params.append(tags)

        if source:
            idx += 1
            conditions.append(f"source = ${idx}")
            params.append(source)

        # Visibility: your entries + entries shared to your org + global entries
        if user_id and org_id:
            idx += 1
            uid_idx = idx
            idx += 1
            oid_idx = idx
            conditions.append(
                f"(user_id = ${uid_idx} OR org_id = ${oid_idx} OR user_id IS NULL)"
            )
            params.append(user_id)
            params.append(org_id)
        elif user_id:
            idx += 1
            conditions.append(f"(user_id = ${idx} OR user_id IS NULL)")
            params.append(user_id)
        elif org_id:
            idx += 1
            conditions.append(f"(org_id = ${idx} OR user_id IS NULL)")
            params.append(org_id)

        if workspace:
            idx += 1
            conditions.append(f"workspace = ${idx}")
            params.append(workspace)

        if project:
            idx += 1
            conditions.append(f"project = ${idx}")
            params.append(project)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        idx += 1
        offset_idx = idx
        params.append(offset)
        idx += 1
        limit_idx = idx
        params.append(limit)

        cols = ("id, title, content, tags, source, user_id,"
                " org_id, workspace, project, archived_at, created_at, updated_at")
        sql = (
            f"SELECT {cols} FROM entries {where}"
            f" ORDER BY updated_at DESC OFFSET ${offset_idx} LIMIT ${limit_idx}"
        )
        rows = await self._pool.fetch(sql, *params)
        return [dict(r) for r in rows]

    # -- Helpers --

    @staticmethod
    def _add_visibility(
        conditions: list[str],
        params: list,
        idx: int,
        user_id: str | None,
        org_id: str | None,
    ) -> int:
        """Add user/org visibility filter. Returns updated idx."""
        if user_id and org_id:
            idx += 1
            uid_idx = idx
            idx += 1
            oid_idx = idx
            conditions.append(
                f"(user_id = ${uid_idx} OR org_id = ${oid_idx} OR user_id IS NULL)"
            )
            params.append(user_id)
            params.append(org_id)
        elif user_id:
            idx += 1
            conditions.append(f"(user_id = ${idx} OR user_id IS NULL)")
            params.append(user_id)
        elif org_id:
            idx += 1
            conditions.append(f"(org_id = ${idx} OR user_id IS NULL)")
            params.append(org_id)
        return idx

    # -- Search (used by fusion) --

    @staticmethod
    def _add_scope(
        conditions: list[str],
        params: list,
        idx: int,
        workspace: str | None,
        project: str | None,
    ) -> int:
        """Add workspace/project filters. Returns updated idx."""
        if workspace:
            idx += 1
            conditions.append(f"workspace = ${idx}")
            params.append(workspace)
        if project:
            idx += 1
            conditions.append(f"project = ${idx}")
            params.append(project)
        return idx

    async def search_semantic(
        self,
        embedding: list[float],
        user_id: str | None = None,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search by vector similarity. Returns entries with distance score."""
        if not self.has_vectors:
            return []

        conditions = ["archived_at IS NULL"]
        params: list = []
        idx = 0

        idx = self._add_visibility(conditions, params, idx, user_id, org_id)
        idx = self._add_scope(conditions, params, idx, workspace, project)

        if tags:
            idx += 1
            conditions.append(f"tags && ${idx}")
            params.append(tags)

        where = f"WHERE {' AND '.join(conditions)}"

        idx += 1
        params.append(str(embedding))
        embed_idx = idx

        idx += 1
        params.append(limit)
        limit_idx = idx

        sql = (
            f"SELECT id, title, content, tags, source, workspace, project,"
            f" archived_at, created_at, updated_at,"
            f" embedding <=> ${embed_idx} AS distance"
            f" FROM entries {where}"
            f" ORDER BY embedding <=> ${embed_idx}"
            f" LIMIT ${limit_idx}"
        )
        rows = await self._pool.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def search_keyword(
        self,
        query: str,
        user_id: str | None = None,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search by Postgres full-text search. Returns entries with rank score."""
        conditions = ["archived_at IS NULL"]
        params: list = []
        idx = 0

        idx += 1
        query_idx = idx
        params.append(query)
        conditions.append(f"search_vector @@ plainto_tsquery('english', ${query_idx})")

        idx = self._add_visibility(conditions, params, idx, user_id, org_id)
        idx = self._add_scope(conditions, params, idx, workspace, project)

        if tags:
            idx += 1
            conditions.append(f"tags && ${idx}")
            params.append(tags)

        where = f"WHERE {' AND '.join(conditions)}"

        idx += 1
        params.append(limit)
        limit_idx = idx

        sql = (
            f"SELECT id, title, content, tags, source, workspace, project,"
            f" archived_at, created_at, updated_at,"
            f" ts_rank(search_vector, plainto_tsquery('english', ${query_idx})) AS rank"
            f" FROM entries {where}"
            f" ORDER BY rank DESC"
            f" LIMIT ${limit_idx}"
        )
        rows = await self._pool.fetch(sql, *params)
        return [dict(r) for r in rows]

    # -- Similarity & Deduplication --

    async def find_similar(
        self,
        embedding: list[float],
        threshold: float = 0.15,
        workspace: str | None = None,
        project: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        exclude_ids: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Find entries similar to the given embedding within cosine distance threshold."""
        if not self.has_vectors:
            return []

        conditions = ["archived_at IS NULL", "embedding IS NOT NULL"]
        params: list = []
        idx = 0

        idx = self._add_visibility(conditions, params, idx, user_id, org_id)
        idx = self._add_scope(conditions, params, idx, workspace, project)

        if exclude_ids:
            idx += 1
            conditions.append(f"NOT (id = ANY(${idx}))")
            params.append(exclude_ids)

        idx += 1
        params.append(str(embedding))
        embed_idx = idx

        idx += 1
        params.append(threshold)
        thresh_idx = idx

        idx += 1
        params.append(limit)
        limit_idx = idx

        where = f"WHERE {' AND '.join(conditions)}"

        sql = (
            f"SELECT id, title, content, tags, source, workspace, project,"
            f" archived_at, created_at, updated_at,"
            f" embedding <=> ${embed_idx} AS distance"
            f" FROM entries {where}"
            f" AND embedding <=> ${embed_idx} < ${thresh_idx}"
            f" ORDER BY embedding <=> ${embed_idx}"
            f" LIMIT ${limit_idx}"
        )
        rows = await self._pool.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def find_duplicate_clusters(
        self,
        workspace: str | None = None,
        project: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        threshold: float = 0.12,
        limit: int = 50,
    ) -> list[list[dict]]:
        """Find clusters of near-duplicate entries by embedding similarity.

        Uses a self-join to find all pairs within threshold, then groups
        connected pairs into clusters via union-find.
        """
        if not self.has_vectors:
            return []

        conditions = [
            "a.archived_at IS NULL",
            "b.archived_at IS NULL",
            "a.embedding IS NOT NULL",
            "b.embedding IS NOT NULL",
            "a.id < b.id",
        ]
        params: list = []
        idx = 0

        idx += 1
        params.append(threshold)
        thresh_idx = idx

        if workspace:
            idx += 1
            conditions.append(f"a.workspace = ${idx}")
            conditions.append(f"b.workspace = ${idx}")
            params.append(workspace)

        if project:
            idx += 1
            conditions.append(f"a.project = ${idx}")
            conditions.append(f"b.project = ${idx}")
            params.append(project)

        # Visibility scoping for both sides
        if user_id and org_id:
            idx += 1
            uid_idx = idx
            idx += 1
            oid_idx = idx
            conditions.append(
                f"(a.user_id = ${uid_idx} OR a.org_id = ${oid_idx} OR a.user_id IS NULL)"
            )
            conditions.append(
                f"(b.user_id = ${uid_idx} OR b.org_id = ${oid_idx} OR b.user_id IS NULL)"
            )
            params.append(user_id)
            params.append(org_id)
        elif user_id:
            idx += 1
            conditions.append(f"(a.user_id = ${idx} OR a.user_id IS NULL)")
            conditions.append(f"(b.user_id = ${idx} OR b.user_id IS NULL)")
            params.append(user_id)
        elif org_id:
            idx += 1
            conditions.append(f"(a.org_id = ${idx} OR a.user_id IS NULL)")
            conditions.append(f"(b.org_id = ${idx} OR b.user_id IS NULL)")
            params.append(org_id)

        idx += 1
        params.append(limit)
        limit_idx = idx

        where = f"WHERE {' AND '.join(conditions)}"

        sql = (
            f"SELECT a.id AS id_a, a.title AS title_a, a.content AS content_a,"
            f" a.tags AS tags_a, a.source AS source_a,"
            f" a.workspace AS workspace_a, a.created_at AS created_a, a.updated_at AS updated_a,"
            f" b.id AS id_b, b.title AS title_b, b.content AS content_b,"
            f" b.tags AS tags_b, b.source AS source_b,"
            f" b.workspace AS workspace_b, b.created_at AS created_b, b.updated_at AS updated_b,"
            f" a.embedding <=> b.embedding AS distance"
            f" FROM entries a JOIN entries b ON a.id < b.id"
            f" {where}"
            f" AND a.embedding <=> b.embedding < ${thresh_idx}"
            f" ORDER BY a.embedding <=> b.embedding"
            f" LIMIT ${limit_idx}"
        )
        rows = await self._pool.fetch(sql, *params)

        if not rows:
            return []

        # Union-find to group connected pairs into clusters
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(x: str, y: str) -> None:
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        entry_map: dict[str, dict] = {}
        pair_distances: list[tuple[str, str, float]] = []

        for row in rows:
            id_a, id_b = row["id_a"], row["id_b"]
            distance = row["distance"]
            union(id_a, id_b)
            pair_distances.append((id_a, id_b, distance))

            if id_a not in entry_map:
                entry_map[id_a] = {
                    "id": id_a, "title": row["title_a"], "content": row["content_a"],
                    "tags": row["tags_a"],
                    "source": row["source_a"], "workspace": row["workspace_a"],
                    "created_at": row["created_a"], "updated_at": row["updated_a"],
                }
            if id_b not in entry_map:
                entry_map[id_b] = {
                    "id": id_b, "title": row["title_b"], "content": row["content_b"],
                    "tags": row["tags_b"],
                    "source": row["source_b"], "workspace": row["workspace_b"],
                    "created_at": row["created_b"], "updated_at": row["updated_b"],
                }

        # Group by cluster root
        clusters_map: dict[str, list[dict]] = {}
        for eid in entry_map:
            root = find(eid)
            clusters_map.setdefault(root, []).append(entry_map[eid])

        # Add min distance to each entry within its cluster
        for id_a, id_b, distance in pair_distances:
            entry_a = entry_map[id_a]
            entry_b = entry_map[id_b]
            entry_a["min_distance"] = min(entry_a.get("min_distance", 1.0), distance)
            entry_b["min_distance"] = min(entry_b.get("min_distance", 1.0), distance)

        return [cluster for cluster in clusters_map.values() if len(cluster) > 1]

    async def merge_entries(
        self,
        source_ids: list[str],
        title: str,
        content: str,
        tags: list[str] | None = None,
        source: str | None = None,
        embedding: list[float] | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
    ) -> str:
        """Atomically merge entries: create new entry + archive sources with lineage."""
        new_id = uuid4().hex
        now = datetime.now(UTC)
        lineage_source = source or f"merged_from:{','.join(source_ids)}"

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Create merged entry
                if embedding and self.has_vectors:
                    await conn.execute(
                        """INSERT INTO entries
                           (id, title, content, tags, source,
                            embedding, user_id, org_id, workspace, project,
                            created_at, updated_at)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                        new_id, title, content, tags or [],
                        lineage_source, str(embedding),
                        user_id, org_id, workspace, project, now, now,
                    )
                else:
                    await conn.execute(
                        """INSERT INTO entries
                           (id, title, content, tags, source,
                            user_id, org_id, workspace, project,
                            created_at, updated_at)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
                        new_id, title, content, tags or [],
                        lineage_source,
                        user_id, org_id, workspace, project, now, now,
                    )

                # Archive sources with lineage
                await conn.execute(
                    """UPDATE entries
                       SET archived_at = $2,
                           source = COALESCE(source, '') || $1,
                           updated_at = $2
                       WHERE id = ANY($3)""",
                    f" -> merged_into:{new_id}",
                    now,
                    source_ids,
                )

        return new_id

    async def upsert_entry(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
        source: str | None = None,
        embedding: list[float] | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
        dedupe_threshold: float = 0.10,
    ) -> tuple[str, bool]:
        """Create or update an entry. If a similar entry exists within threshold, update it.

        Returns (entry_id, was_updated).
        """
        if embedding and self.has_vectors:
            similar = await self.find_similar(
                embedding,
                threshold=dedupe_threshold,
                workspace=workspace,
                project=project,
                user_id=user_id,
                org_id=org_id,
                limit=1,
            )
            if similar:
                match_id = similar[0]["id"]
                await self.update_entry(
                    match_id,
                    title=title,
                    content=content,
                    tags=tags,
                    source=source,
                    embedding=embedding,
                )
                return match_id, True

        entry_id = await self.create_entry(
            title=title,
            content=content,
            tags=tags,
            source=source,
            embedding=embedding,
            user_id=user_id,
            org_id=org_id,
            workspace=workspace,
            project=project,
        )
        return entry_id, False

    async def upsert_entry_by_path(
        self,
        source_path: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
        source: str | None = None,
        embedding: list[float] | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
        archived: bool = False,
    ) -> tuple[str, bool]:
        """Create or update the entry identified by ``source_path`` within scope.

        Identity is the bundle-relative path, scoped to (org, workspace,
        project) — deterministic, so re-pushing a bundle updates in place rather
        than duplicating. The bundle is the source of truth, so ``archived``
        mirrors the frontmatter on every push. Returns (entry_id, was_updated).
        """
        existing = await self._pool.fetchval(
            """SELECT id FROM entries
               WHERE source_path = $1
                 AND COALESCE(org_id, '') = COALESCE($2, '')
                 AND COALESCE(workspace, '') = COALESCE($3, '')
                 AND COALESCE(project, '') = COALESCE($4, '')""",
            source_path,
            org_id,
            workspace,
            project,
        )

        now = datetime.now(UTC)
        archived_at = now if archived else None
        use_vec = bool(embedding) and self.has_vectors
        if existing:
            if use_vec:
                await self._pool.execute(
                    """UPDATE entries
                       SET title=$2, content=$3, tags=$4, source=$5,
                           embedding=$6, archived_at=$7, updated_at=$8
                       WHERE id=$1""",
                    existing, title, content, tags or [], source,
                    str(embedding), archived_at, now,
                )
            else:
                await self._pool.execute(
                    """UPDATE entries
                       SET title=$2, content=$3, tags=$4, source=$5,
                           archived_at=$6, updated_at=$7
                       WHERE id=$1""",
                    existing, title, content, tags or [], source,
                    archived_at, now,
                )
            return existing, True

        entry_id = uuid4().hex
        if use_vec:
            await self._pool.execute(
                """INSERT INTO entries
                   (id, title, content, tags, source, source_path,
                    embedding, user_id, org_id, workspace, project,
                    archived_at, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$13)""",
                entry_id, title, content, tags or [], source, source_path,
                str(embedding), user_id, org_id, workspace, project, archived_at, now,
            )
        else:
            await self._pool.execute(
                """INSERT INTO entries
                   (id, title, content, tags, source, source_path,
                    user_id, org_id, workspace, project, archived_at,
                    created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$12)""",
                entry_id, title, content, tags or [], source, source_path,
                user_id, org_id, workspace, project, archived_at, now,
            )
        return entry_id, False

    # -- Links --

    async def find_entries_by_titles(
        self,
        normalized_titles: list[str],
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> dict[str, str]:
        """Resolve normalized (lowercased) titles to entry IDs within visibility.

        On collision the most recently updated entry wins.
        """
        if not normalized_titles:
            return {}

        conditions = ["LOWER(title) = ANY($1)"]
        params: list = [normalized_titles]
        idx = 1
        idx = self._add_visibility(conditions, params, idx, user_id, org_id)

        sql = (
            f"SELECT DISTINCT ON (LOWER(title)) LOWER(title) AS norm_title, id"
            f" FROM entries WHERE {' AND '.join(conditions)}"
            f" ORDER BY LOWER(title), updated_at DESC"
        )
        rows = await self._pool.fetch(sql, *params)
        return {r["norm_title"]: r["id"] for r in rows}

    async def replace_entry_links(
        self, entry_id: str, org_id: str | None, links: list[dict]
    ) -> None:
        """Replace all outgoing link edges for an entry."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM links WHERE source_type = 'entry' AND source_id = $1",
                    entry_id,
                )
                for link in links:
                    await conn.execute(
                        """INSERT INTO links
                           (id, org_id, source_type, source_id, target_type,
                            target_id, target_ref, link_text, normalized_target)
                           VALUES ($1, $2, 'entry', $3, $4, $5, $6, $7, $8)""",
                        uuid4().hex,
                        org_id,
                        entry_id,
                        link["target_type"],
                        link.get("target_id"),
                        link.get("target_ref"),
                        link["link_text"],
                        link["normalized_target"],
                    )

    async def get_outgoing_links(self, entry_id: str) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT l.id, l.target_type, l.target_id, l.target_ref, l.link_text,"
            " l.normalized_target, l.created_at,"
            " e.title AS target_title, e.workspace AS target_workspace,"
            " e.project AS target_project"
            " FROM links l LEFT JOIN entries e ON l.target_id = e.id"
            " WHERE l.source_type = 'entry' AND l.source_id = $1"
            " ORDER BY l.created_at",
            entry_id,
        )
        return [dict(r) for r in rows]

    async def get_backlinks(
        self,
        entry_id: str,
        normalized_title: str,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> list[dict]:
        """Links pointing at this entry — resolved by ID, or unresolved
        wikilinks whose normalized target matches this entry's title.

        Source entries are visibility-filtered so titles don't leak across orgs.
        """
        conditions = [
            "(l.target_type = 'entry' AND l.target_id = $1)"
            " OR (l.target_type = 'unresolved' AND l.normalized_target = $2)"
        ]
        params: list = [entry_id, normalized_title]
        idx = 2

        vis: list[str] = []
        idx = self._add_visibility(vis, params, idx, user_id, org_id)
        conditions = [f"({conditions[0]})"] + [
            v.replace("user_id", "e.user_id").replace("org_id", "e.org_id") for v in vis
        ]

        sql = (
            f"SELECT l.id, l.source_id, l.link_text, l.target_type, l.created_at,"
            f" e.title AS source_title, e.workspace AS source_workspace,"
            f" e.project AS source_project"
            f" FROM links l JOIN entries e ON l.source_id = e.id"
            f" WHERE l.source_type = 'entry' AND {' AND '.join(conditions)}"
            f" ORDER BY l.created_at DESC"
        )
        rows = await self._pool.fetch(sql, *params)
        return [dict(r) for r in rows]

    # -- API Keys --

    async def create_token(
        self,
        name: str,
        token_hash: str,
        token_prefix: str,
        user_id: str | None = None,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
        role: str = "editor",
    ) -> str:
        token_id = uuid4().hex
        await self._pool.execute(
            "INSERT INTO tokens"
            " (id, name, token_hash, token_prefix, user_id, org_id, workspace, project, role)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
            token_id, name, token_hash, token_prefix, user_id, org_id, workspace, project, role,
        )
        return token_id

    async def get_token(self, token_id: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT id, name, token_prefix, user_id, org_id, workspace, project, role,"
            " created_at, last_used_at FROM tokens WHERE id = $1",
            token_id,
        )
        return dict(row) if row else None

    async def get_token_by_hash(self, token_hash: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT id, name, token_prefix, user_id, org_id, workspace, project, role,"
            " created_at, last_used_at FROM tokens WHERE token_hash = $1",
            token_hash,
        )
        return dict(row) if row else None

    async def touch_token(self, token_id: str) -> None:
        await self._pool.execute(
            "UPDATE tokens SET last_used_at = $1 WHERE id = $2",
            datetime.now(UTC), token_id,
        )

    async def list_tokens(self) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT id, name, token_prefix, user_id, org_id, workspace, project, role,"
            " created_at, last_used_at FROM tokens ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]

    async def delete_token(self, token_id: str) -> bool:
        result = await self._pool.execute("DELETE FROM tokens WHERE id = $1", token_id)
        return result == "DELETE 1"

    async def list_tokens_for_user(self, user_id: str) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT id, name, token_prefix, user_id, org_id, workspace, project, role,"
            " created_at, last_used_at FROM tokens WHERE user_id = $1"
            " ORDER BY created_at DESC",
            user_id,
        )
        return [dict(r) for r in rows]

    # -- Users --

    async def get_or_create_user(self, email: str) -> dict:
        row = await self._pool.fetchrow("SELECT * FROM users WHERE email = $1", email)
        if row:
            return dict(row)
        user_id = uuid4().hex
        await self._pool.execute(
            "INSERT INTO users (id, email) VALUES ($1, $2)", user_id, email
        )
        return {"id": user_id, "email": email, "display_name": None,
                "created_at": datetime.now(UTC)}

    async def get_user(self, user_id: str) -> dict | None:
        row = await self._pool.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        return dict(row) if row else None

    async def update_user(self, user_id: str, display_name: str) -> None:
        await self._pool.execute(
            "UPDATE users SET display_name = $1 WHERE id = $2", display_name, user_id
        )

    # -- Orgs --

    async def create_org(self, name: str, slug: str, creator_id: str) -> str:
        org_id = uuid4().hex
        await self._pool.execute(
            "INSERT INTO orgs (id, name, slug) VALUES ($1, $2, $3)",
            org_id, name, slug,
        )
        await self._pool.execute(
            "INSERT INTO org_members (org_id, user_id, role) VALUES ($1, $2, 'owner')",
            org_id, creator_id,
        )
        return org_id

    async def get_org(self, org_id: str) -> dict | None:
        row = await self._pool.fetchrow("SELECT * FROM orgs WHERE id = $1", org_id)
        return dict(row) if row else None

    async def get_org_by_slug(self, slug: str) -> dict | None:
        row = await self._pool.fetchrow("SELECT * FROM orgs WHERE slug = $1", slug)
        return dict(row) if row else None

    async def list_user_orgs(self, user_id: str) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT o.*, om.role FROM orgs o"
            " JOIN org_members om ON o.id = om.org_id"
            " WHERE om.user_id = $1 ORDER BY o.name",
            user_id,
        )
        return [dict(r) for r in rows]

    async def add_org_member(self, org_id: str, user_id: str, role: str = "member") -> None:
        await self._pool.execute(
            "INSERT INTO org_members (org_id, user_id, role) VALUES ($1, $2, $3)"
            " ON CONFLICT (org_id, user_id) DO NOTHING",
            org_id, user_id, role,
        )

    async def get_org_role(self, org_id: str, user_id: str) -> str | None:
        row = await self._pool.fetchrow(
            "SELECT role FROM org_members WHERE org_id = $1 AND user_id = $2",
            org_id, user_id,
        )
        return row["role"] if row else None

    async def get_user_default_org(self, user_id: str) -> str | None:
        row = await self._pool.fetchrow(
            "SELECT default_org_id FROM users WHERE id = $1", user_id
        )
        return row["default_org_id"] if row else None

    async def set_user_default_org(self, user_id: str, org_id: str | None) -> None:
        await self._pool.execute(
            "UPDATE users SET default_org_id = $2 WHERE id = $1", user_id, org_id
        )

    async def list_org_members(self, org_id: str) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT u.id, u.email, u.display_name, om.role, om.joined_at"
            " FROM org_members om JOIN users u ON om.user_id = u.id"
            " WHERE om.org_id = $1 ORDER BY om.joined_at",
            org_id,
        )
        return [dict(r) for r in rows]

    async def remove_org_member(self, org_id: str, user_id: str) -> bool:
        result = await self._pool.execute(
            "DELETE FROM org_members WHERE org_id = $1 AND user_id = $2",
            org_id, user_id,
        )
        return result == "DELETE 1"

    # -- Workspaces --

    async def create_workspace(self, org_id: str, name: str, slug: str) -> str:
        ws_id = uuid4().hex
        await self._pool.execute(
            "INSERT INTO workspaces (id, org_id, name, slug) VALUES ($1, $2, $3, $4)",
            ws_id, org_id, name, slug,
        )
        return ws_id

    async def get_workspace(self, ws_id: str) -> dict | None:
        row = await self._pool.fetchrow("SELECT * FROM workspaces WHERE id = $1", ws_id)
        return dict(row) if row else None

    async def list_workspaces(self, org_id: str) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM workspaces WHERE org_id = $1 ORDER BY name", org_id
        )
        return [dict(r) for r in rows]

    async def delete_workspace(self, ws_id: str) -> bool:
        result = await self._pool.execute("DELETE FROM workspaces WHERE id = $1", ws_id)
        return result == "DELETE 1"

    # -- Projects --

    async def create_project(self, ws_id: str, name: str, slug: str) -> str:
        proj_id = uuid4().hex
        await self._pool.execute(
            "INSERT INTO projects (id, workspace_id, name, slug) VALUES ($1, $2, $3, $4)",
            proj_id, ws_id, name, slug,
        )
        return proj_id

    async def get_project(self, proj_id: str) -> dict | None:
        row = await self._pool.fetchrow("SELECT * FROM projects WHERE id = $1", proj_id)
        return dict(row) if row else None

    async def list_projects(self, ws_id: str) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM projects WHERE workspace_id = $1 ORDER BY name", ws_id
        )
        return [dict(r) for r in rows]

    async def delete_project(self, proj_id: str) -> bool:
        result = await self._pool.execute("DELETE FROM projects WHERE id = $1", proj_id)
        return result == "DELETE 1"

    # -- KV stores --

    async def create_kv_store(
        self,
        slug: str,
        title: str,
        description: str | None = None,
        visibility: str = "org",
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
        created_by_user_id: str | None = None,
        source: str = "server",
    ) -> str:
        store_id = uuid4().hex
        now = datetime.now(UTC)
        await self._pool.execute(
            """INSERT INTO kv_stores
               (id, org_id, workspace, project, slug, title, description,
                visibility, created_by_user_id, source, created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $11)""",
            store_id, org_id, workspace, project, slug, title, description,
            visibility, created_by_user_id, source, now,
        )
        return store_id

    async def get_kv_store(
        self,
        store_id: str,
        *,
        user_id: str | None = None,  # noqa: ARG002 — call-site uniformity; kv stores aren't user-scoped
        org_id: str | None = None,
        trusted: bool = False,
    ) -> dict | None:
        """Fetch a kv store by id, enforcing org visibility unless ``trusted``.

        Stores are visible to their org plus global (org_id NULL). Pass
        ``**ctx.view_filter``; the user_id kwarg is accepted but unused so the
        same call shape works for entries and kv stores.
        """
        if trusted:
            row = await self._pool.fetchrow(
                "SELECT * FROM kv_stores WHERE id = $1", store_id
            )
        else:
            row = await self._pool.fetchrow(
                "SELECT * FROM kv_stores WHERE id = $1"
                " AND (org_id IS NULL OR org_id = $2)",
                store_id, org_id,
            )
        return dict(row) if row else None

    async def find_kv_store(
        self,
        slug: str,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
    ) -> dict | None:
        """Find a kv store by slug within org visibility.

        workspace/project narrow the match when provided; an exact scope
        match wins over a broader (NULL-scoped) one.
        """
        conditions = ["slug = $1"]
        params: list = [slug]
        idx = 1

        if org_id:
            idx += 1
            conditions.append(f"(org_id = ${idx} OR org_id IS NULL)")
            params.append(org_id)

        if workspace:
            idx += 1
            conditions.append(f"(workspace = ${idx} OR workspace IS NULL)")
            params.append(workspace)

        if project:
            idx += 1
            conditions.append(f"(project = ${idx} OR project IS NULL)")
            params.append(project)

        sql = (
            f"SELECT * FROM kv_stores WHERE {' AND '.join(conditions)}"
            f" ORDER BY org_id NULLS LAST, workspace NULLS LAST, project NULLS LAST"
            f" LIMIT 1"
        )
        row = await self._pool.fetchrow(sql, *params)
        return dict(row) if row else None

    async def list_kv_stores(
        self,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
    ) -> list[dict]:
        conditions = []
        params: list = []
        idx = 0

        if org_id:
            idx += 1
            conditions.append(f"(org_id = ${idx} OR org_id IS NULL)")
            params.append(org_id)

        idx = self._add_scope(conditions, params, idx, workspace, project)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await self._pool.fetch(
            f"SELECT s.*,"
            f" (SELECT COUNT(*) FROM kv_pairs p WHERE p.store_id = s.id)"
            f" AS key_count"
            f" FROM kv_stores s {where} ORDER BY s.slug"
        , *params)
        return [dict(r) for r in rows]

    async def delete_kv_store(self, store_id: str) -> bool:
        result = await self._pool.execute(
            "DELETE FROM kv_stores WHERE id = $1", store_id
        )
        return result == "DELETE 1"

    # -- KV pairs --

    async def set_kv_pair(
        self,
        store_id: str,
        key: str,
        value,
        value_type: str = "json",
        summary: str | None = None,
        org_id: str | None = None,
        created_by_user_id: str | None = None,
    ) -> str:
        pair_id = uuid4().hex
        now = datetime.now(UTC)
        row = await self._pool.fetchrow(
            """INSERT INTO kv_pairs
               (id, org_id, store_id, key, value, value_type, summary,
                created_by_user_id, created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9)
               ON CONFLICT (store_id, key) DO UPDATE SET
                 value = EXCLUDED.value,
                 value_type = EXCLUDED.value_type,
                 summary = COALESCE(EXCLUDED.summary, kv_pairs.summary),
                 updated_at = EXCLUDED.updated_at
               RETURNING id""",
            pair_id, org_id, store_id, key, value, value_type, summary,
            created_by_user_id, now,
        )
        await self._pool.execute(
            "UPDATE kv_stores SET updated_at = $1 WHERE id = $2", now, store_id
        )
        return row["id"]

    async def get_kv_pair(
        self,
        store_id: str,
        key: str,
        *,
        user_id: str | None = None,  # noqa: ARG002 — call-site uniformity; pairs inherit store scope
        org_id: str | None = None,
        trusted: bool = False,
    ) -> dict | None:
        """Fetch a kv pair, enforcing its store's org visibility unless
        ``trusted``. Pass ``**ctx.view_filter``."""
        if trusted:
            row = await self._pool.fetchrow(
                "SELECT * FROM kv_pairs WHERE store_id = $1 AND key = $2",
                store_id, key,
            )
        else:
            row = await self._pool.fetchrow(
                "SELECT p.* FROM kv_pairs p"
                " JOIN kv_stores s ON s.id = p.store_id"
                " WHERE p.store_id = $1 AND p.key = $2"
                " AND (s.org_id IS NULL OR s.org_id = $3)",
                store_id, key, org_id,
            )
        return dict(row) if row else None

    async def list_kv_pairs(self, store_id: str) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM kv_pairs WHERE store_id = $1 ORDER BY key",
            store_id,
        )
        return [dict(r) for r in rows]

    async def delete_kv_pair(self, store_id: str, key: str) -> bool:
        result = await self._pool.execute(
            "DELETE FROM kv_pairs WHERE store_id = $1 AND key = $2",
            store_id, key,
        )
        return result == "DELETE 1"

    async def list_recent_kv_pairs(
        self,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Recently written kv pairs (with their store's slug + scope) for the
        activity feed, newest first. Org-visible (own org + global)."""
        conditions = []
        params: list = []
        idx = 0

        if org_id:
            idx += 1
            conditions.append(f"(s.org_id = ${idx} OR s.org_id IS NULL)")
            params.append(org_id)
        if workspace:
            idx += 1
            conditions.append(f"s.workspace = ${idx}")
            params.append(workspace)
        if project:
            idx += 1
            conditions.append(f"s.project = ${idx}")
            params.append(project)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        idx += 1
        params.append(limit)
        rows = await self._pool.fetch(
            f"SELECT p.id, p.key, p.value_type, p.created_at, p.updated_at,"
            f" s.slug AS store_slug, s.workspace, s.project"
            f" FROM kv_pairs p JOIN kv_stores s ON s.id = p.store_id"
            f" {where} ORDER BY p.updated_at DESC LIMIT ${idx}",
            *params,
        )
        return [dict(r) for r in rows]

    # -- Attachments --

    async def create_attachment(
        self,
        entry_id: str,
        kind: str,
        filename: str,
        media_type: str,
        storage_key: str,
        byte_size: int,
        org_id: str | None = None,
        description: str | None = None,
        role: str | None = None,
        public: bool = False,
        created_by_user_id: str | None = None,
        att_id: str | None = None,
    ) -> str:
        att_id = att_id or uuid4().hex
        await self._pool.execute(
            """INSERT INTO attachments
               (id, org_id, entry_id, kind, filename, media_type, storage_key,
                byte_size, description, role, public, created_by_user_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
            att_id, org_id, entry_id, kind, filename, media_type, storage_key,
            byte_size, description, role, public, created_by_user_id,
        )
        return att_id

    async def get_attachment(self, att_id: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM attachments WHERE id = $1", att_id
        )
        return dict(row) if row else None

    async def list_attachments(self, entry_id: str) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM attachments WHERE entry_id = $1 ORDER BY created_at",
            entry_id,
        )
        return [dict(r) for r in rows]

    async def delete_attachment(self, att_id: str) -> bool:
        result = await self._pool.execute(
            "DELETE FROM attachments WHERE id = $1", att_id
        )
        return result == "DELETE 1"

    # -- Email OTP --

    async def create_email_token(self, email: str, code: str, ttl_minutes: int = 10) -> str:
        token_id = uuid4().hex
        expires = datetime.now(UTC) + timedelta(minutes=ttl_minutes)
        await self._pool.execute(
            "INSERT INTO email_tokens (id, email, code, expires_at) VALUES ($1, $2, $3, $4)",
            token_id, email, code, expires,
        )
        return token_id

    async def verify_email_token(self, email: str, code: str) -> bool:
        row = await self._pool.fetchrow(
            "SELECT id FROM email_tokens"
            " WHERE email = $1 AND code = $2 AND used = FALSE AND expires_at > NOW()"
            " ORDER BY created_at DESC LIMIT 1",
            email, code,
        )
        if not row:
            return False
        await self._pool.execute(
            "UPDATE email_tokens SET used = TRUE WHERE id = $1", row["id"]
        )
        return True

    # -- Sessions --

    async def create_session(self, user_id: str, ttl_hours: int = 720) -> str:
        session_id = uuid4().hex
        expires = datetime.now(UTC) + timedelta(hours=ttl_hours)
        await self._pool.execute(
            "INSERT INTO sessions (id, user_id, expires_at) VALUES ($1, $2, $3)",
            session_id, user_id, expires,
        )
        return session_id

    async def get_session(self, session_id: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT s.*, u.email, u.display_name FROM sessions s"
            " JOIN users u ON s.user_id = u.id"
            " WHERE s.id = $1 AND s.expires_at > NOW()",
            session_id,
        )
        return dict(row) if row else None

    async def delete_session(self, session_id: str) -> None:
        await self._pool.execute("DELETE FROM sessions WHERE id = $1", session_id)

    # -- Activity log --

    async def record_activity(
        self,
        *,
        action: str,
        subject_type: str,
        subject_id: str | None = None,
        subject_title: str | None = None,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
        actor_user_id: str | None = None,
        actor_type: str = "unknown",
        actor_ref: str | None = None,
        metadata: dict | None = None,
    ) -> str | None:
        """Append one event to the activity log.

        Best-effort by design: a logging failure must never turn a write that
        already succeeded into a failed request, so this swallows and logs its
        own errors rather than propagating. (When revision tables land they'll
        be written inside the mutation's own transaction; the activity feed is
        a denormalized read model on top.) Returns the event id, or None if
        recording failed.
        """
        event_id = uuid4().hex
        try:
            await self._pool.execute(
                """INSERT INTO activity_events
                   (id, org_id, workspace, project, actor_user_id, actor_type,
                    actor_ref, action, subject_type, subject_id, subject_title,
                    metadata_json, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)""",
                event_id, org_id, workspace, project, actor_user_id, actor_type,
                actor_ref, action, subject_type, subject_id, subject_title,
                metadata or {}, datetime.now(UTC),
            )
        except Exception:
            logger.exception("Failed to record activity event %s", action)
            return None
        return event_id

    async def list_activity(
        self,
        *,
        org_id: str | None = None,
        user_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
        limit: int = 50,
        trusted: bool = False,
    ) -> list[dict]:
        """Recent activity events, newest first.

        Fail-closed visibility mirrors the rest of the store: a tenant caller
        sees their active-org events, events they performed, and truly-global
        system events (org and actor both NULL). ``trusted`` (static key /
        unrestricted) sees everything. workspace/project narrow the result.
        """
        conditions: list[str] = []
        params: list = []

        if not trusted:
            # org events you're in, events you performed, or fully-global ones.
            params.append(org_id)
            oid = len(params)
            params.append(user_id)
            uid = len(params)
            conditions.append(
                f"((${oid}::text IS NOT NULL AND org_id = ${oid})"
                f" OR (${uid}::text IS NOT NULL AND actor_user_id = ${uid})"
                f" OR (org_id IS NULL AND actor_user_id IS NULL))"
            )
        if workspace is not None:
            params.append(workspace)
            conditions.append(f"workspace = ${len(params)}")
        if project is not None:
            params.append(project)
            conditions.append(f"project = ${len(params)}")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = await self._pool.fetch(
            f"SELECT id, org_id, workspace, project, actor_user_id, actor_type,"
            f" actor_ref, action, subject_type, subject_id, subject_title,"
            f" metadata_json, created_at FROM activity_events"
            f" {where} ORDER BY created_at DESC LIMIT ${len(params)}",
            *params,
        )
        return [dict(r) for r in rows]
