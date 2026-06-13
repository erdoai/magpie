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
        category: str = "resource",
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
                   (id, title, content, category, tags, source,
                    embedding, user_id, org_id, workspace, project,
                    created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)""",
                entry_id,
                title,
                content,
                category,
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
                   (id, title, content, category, tags, source,
                    user_id, org_id, workspace, project,
                    created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                entry_id,
                title,
                content,
                category,
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
            "id, title, content, category, tags, source, user_id, org_id,"
            " workspace, project, created_at, updated_at"
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
        allowed = {"title", "content", "category", "tags", "source"}
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
            "UPDATE entries SET category = 'archive', updated_at = $1 WHERE id = $2",
            datetime.now(UTC),
            entry_id,
        )
        return result == "UPDATE 1"

    async def list_entries(
        self,
        category: str | None = None,
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

        if category:
            idx += 1
            conditions.append(f"category = ${idx}")
            params.append(category)

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

        cols = ("id, title, content, category, tags, source, user_id,"
                " org_id, workspace, project, created_at, updated_at")
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
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search by vector similarity. Returns entries with distance score."""
        if not self.has_vectors:
            return []

        conditions = ["category != 'archive'"]
        params: list = []
        idx = 0

        idx = self._add_visibility(conditions, params, idx, user_id, org_id)
        idx = self._add_scope(conditions, params, idx, workspace, project)

        if category:
            idx += 1
            conditions.append(f"category = ${idx}")
            params.append(category)

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
            f"SELECT id, title, content, category, tags, source, workspace, project,"
            f" created_at, updated_at,"
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
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search by Postgres full-text search. Returns entries with rank score."""
        conditions = ["category != 'archive'"]
        params: list = []
        idx = 0

        idx += 1
        query_idx = idx
        params.append(query)
        conditions.append(f"search_vector @@ plainto_tsquery('english', ${query_idx})")

        idx = self._add_visibility(conditions, params, idx, user_id, org_id)
        idx = self._add_scope(conditions, params, idx, workspace, project)

        if category:
            idx += 1
            conditions.append(f"category = ${idx}")
            params.append(category)

        if tags:
            idx += 1
            conditions.append(f"tags && ${idx}")
            params.append(tags)

        where = f"WHERE {' AND '.join(conditions)}"

        idx += 1
        params.append(limit)
        limit_idx = idx

        sql = (
            f"SELECT id, title, content, category, tags, source, workspace, project,"
            f" created_at, updated_at,"
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

        conditions = ["category != 'archive'", "embedding IS NOT NULL"]
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
            f"SELECT id, title, content, category, tags, source, workspace, project,"
            f" created_at, updated_at,"
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
            "a.category != 'archive'",
            "b.category != 'archive'",
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
            f" a.category AS category_a, a.tags AS tags_a, a.source AS source_a,"
            f" a.workspace AS workspace_a, a.created_at AS created_a, a.updated_at AS updated_a,"
            f" b.id AS id_b, b.title AS title_b, b.content AS content_b,"
            f" b.category AS category_b, b.tags AS tags_b, b.source AS source_b,"
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
                    "category": row["category_a"], "tags": row["tags_a"],
                    "source": row["source_a"], "workspace": row["workspace_a"],
                    "created_at": row["created_a"], "updated_at": row["updated_a"],
                }
            if id_b not in entry_map:
                entry_map[id_b] = {
                    "id": id_b, "title": row["title_b"], "content": row["content_b"],
                    "category": row["category_b"], "tags": row["tags_b"],
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
        category: str = "resource",
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
                           (id, title, content, category, tags, source,
                            embedding, user_id, org_id, workspace, project,
                            created_at, updated_at)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)""",
                        new_id, title, content, category, tags or [],
                        lineage_source, str(embedding),
                        user_id, org_id, workspace, project, now, now,
                    )
                else:
                    await conn.execute(
                        """INSERT INTO entries
                           (id, title, content, category, tags, source,
                            user_id, org_id, workspace, project,
                            created_at, updated_at)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                        new_id, title, content, category, tags or [],
                        lineage_source,
                        user_id, org_id, workspace, project, now, now,
                    )

                # Archive sources with lineage
                await conn.execute(
                    """UPDATE entries
                       SET category = 'archive',
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
        category: str = "resource",
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
                    category=category,
                    tags=tags,
                    source=source,
                    embedding=embedding,
                )
                return match_id, True

        entry_id = await self.create_entry(
            title=title,
            content=content,
            category=category,
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
        category: str = "resource",
        tags: list[str] | None = None,
        source: str | None = None,
        embedding: list[float] | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
    ) -> tuple[str, bool]:
        """Create or update the entry identified by ``source_path`` within scope.

        Identity is the bundle-relative path, scoped to (org, workspace,
        project) — deterministic, so re-pushing a bundle updates in place rather
        than duplicating. Returns (entry_id, was_updated).
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

        use_vec = bool(embedding) and self.has_vectors
        if existing:
            if use_vec:
                await self._pool.execute(
                    """UPDATE entries
                       SET title=$2, content=$3, category=$4, tags=$5, source=$6,
                           embedding=$7, updated_at=$8
                       WHERE id=$1""",
                    existing, title, content, category, tags or [], source,
                    str(embedding), datetime.now(UTC),
                )
            else:
                await self._pool.execute(
                    """UPDATE entries
                       SET title=$2, content=$3, category=$4, tags=$5, source=$6,
                           updated_at=$7
                       WHERE id=$1""",
                    existing, title, content, category, tags or [], source,
                    datetime.now(UTC),
                )
            return existing, True

        entry_id = uuid4().hex
        now = datetime.now(UTC)
        if use_vec:
            await self._pool.execute(
                """INSERT INTO entries
                   (id, title, content, category, tags, source, source_path,
                    embedding, user_id, org_id, workspace, project,
                    created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)""",
                entry_id, title, content, category, tags or [], source, source_path,
                str(embedding), user_id, org_id, workspace, project, now, now,
            )
        else:
            await self._pool.execute(
                """INSERT INTO entries
                   (id, title, content, category, tags, source, source_path,
                    user_id, org_id, workspace, project, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
                entry_id, title, content, category, tags or [], source, source_path,
                user_id, org_id, workspace, project, now, now,
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

    async def create_api_key(
        self,
        name: str,
        key_hash: str,
        key_prefix: str,
        user_id: str | None = None,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
        role: str = "editor",
    ) -> str:
        key_id = uuid4().hex
        await self._pool.execute(
            "INSERT INTO api_keys"
            " (id, name, key_hash, key_prefix, user_id, org_id, workspace, project, role)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
            key_id, name, key_hash, key_prefix, user_id, org_id, workspace, project, role,
        )
        return key_id

    async def get_api_key(self, key_id: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT id, name, key_prefix, user_id, org_id, workspace, project, role,"
            " created_at, last_used_at FROM api_keys WHERE id = $1",
            key_id,
        )
        return dict(row) if row else None

    async def get_api_key_by_hash(self, key_hash: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT id, name, key_prefix, user_id, org_id, workspace, project, role,"
            " created_at, last_used_at FROM api_keys WHERE key_hash = $1",
            key_hash,
        )
        return dict(row) if row else None

    async def touch_api_key(self, key_id: str) -> None:
        await self._pool.execute(
            "UPDATE api_keys SET last_used_at = $1 WHERE id = $2",
            datetime.now(UTC), key_id,
        )

    async def list_api_keys(self) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT id, name, key_prefix, user_id, org_id, workspace, project, role,"
            " created_at, last_used_at FROM api_keys ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]

    async def delete_api_key(self, key_id: str) -> bool:
        result = await self._pool.execute("DELETE FROM api_keys WHERE id = $1", key_id)
        return result == "DELETE 1"

    async def list_api_keys_for_user(self, user_id: str) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT id, name, key_prefix, user_id, org_id, workspace, project, role,"
            " created_at, last_used_at FROM api_keys WHERE user_id = $1"
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

    # -- Collections --

    async def create_collection(
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
        col_id = uuid4().hex
        now = datetime.now(UTC)
        await self._pool.execute(
            """INSERT INTO collections
               (id, org_id, workspace, project, slug, title, description,
                visibility, created_by_user_id, source, created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $11)""",
            col_id, org_id, workspace, project, slug, title, description,
            visibility, created_by_user_id, source, now,
        )
        return col_id

    async def get_collection(
        self,
        col_id: str,
        *,
        user_id: str | None = None,  # noqa: ARG002 — call-site uniformity; collections aren't user-scoped
        org_id: str | None = None,
        trusted: bool = False,
    ) -> dict | None:
        """Fetch a collection by id, enforcing org visibility unless ``trusted``.

        Collections are visible to their org plus global (org_id NULL). Pass
        ``**ctx.view_filter``; the user_id kwarg is accepted but unused so the
        same call shape works for entries and collections.
        """
        if trusted:
            row = await self._pool.fetchrow(
                "SELECT * FROM collections WHERE id = $1", col_id
            )
        else:
            row = await self._pool.fetchrow(
                "SELECT * FROM collections WHERE id = $1"
                " AND (org_id IS NULL OR org_id = $2)",
                col_id, org_id,
            )
        return dict(row) if row else None

    async def find_collection(
        self,
        slug: str,
        org_id: str | None = None,
        workspace: str | None = None,
        project: str | None = None,
    ) -> dict | None:
        """Find a collection by slug within org visibility.

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
            f"SELECT * FROM collections WHERE {' AND '.join(conditions)}"
            f" ORDER BY org_id NULLS LAST, workspace NULLS LAST, project NULLS LAST"
            f" LIMIT 1"
        )
        row = await self._pool.fetchrow(sql, *params)
        return dict(row) if row else None

    async def list_collections(
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
            f"SELECT c.*,"
            f" (SELECT COUNT(*) FROM documents d WHERE d.collection_id = c.id)"
            f" AS document_count"
            f" FROM collections c {where} ORDER BY c.slug"
        , *params)
        return [dict(r) for r in rows]

    async def delete_collection(self, col_id: str) -> bool:
        result = await self._pool.execute(
            "DELETE FROM collections WHERE id = $1", col_id
        )
        return result == "DELETE 1"

    # -- Documents --

    async def set_document(
        self,
        collection_id: str,
        key: str,
        value,
        value_type: str = "json",
        summary: str | None = None,
        org_id: str | None = None,
        created_by_user_id: str | None = None,
    ) -> str:
        doc_id = uuid4().hex
        now = datetime.now(UTC)
        row = await self._pool.fetchrow(
            """INSERT INTO documents
               (id, org_id, collection_id, key, value, value_type, summary,
                created_by_user_id, created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9)
               ON CONFLICT (collection_id, key) DO UPDATE SET
                 value = EXCLUDED.value,
                 value_type = EXCLUDED.value_type,
                 summary = COALESCE(EXCLUDED.summary, documents.summary),
                 updated_at = EXCLUDED.updated_at
               RETURNING id""",
            doc_id, org_id, collection_id, key, value, value_type, summary,
            created_by_user_id, now,
        )
        await self._pool.execute(
            "UPDATE collections SET updated_at = $1 WHERE id = $2", now, collection_id
        )
        return row["id"]

    async def get_document(
        self,
        collection_id: str,
        key: str,
        *,
        user_id: str | None = None,  # noqa: ARG002 — call-site uniformity; documents inherit collection scope
        org_id: str | None = None,
        trusted: bool = False,
    ) -> dict | None:
        """Fetch a document, enforcing its collection's org visibility unless
        ``trusted``. Pass ``**ctx.view_filter``."""
        if trusted:
            row = await self._pool.fetchrow(
                "SELECT * FROM documents WHERE collection_id = $1 AND key = $2",
                collection_id, key,
            )
        else:
            row = await self._pool.fetchrow(
                "SELECT d.* FROM documents d"
                " JOIN collections c ON c.id = d.collection_id"
                " WHERE d.collection_id = $1 AND d.key = $2"
                " AND (c.org_id IS NULL OR c.org_id = $3)",
                collection_id, key, org_id,
            )
        return dict(row) if row else None

    async def list_documents(self, collection_id: str) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM documents WHERE collection_id = $1 ORDER BY key",
            collection_id,
        )
        return [dict(r) for r in rows]

    async def delete_document(self, collection_id: str, key: str) -> bool:
        result = await self._pool.execute(
            "DELETE FROM documents WHERE collection_id = $1 AND key = $2",
            collection_id, key,
        )
        return result == "DELETE 1"

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
