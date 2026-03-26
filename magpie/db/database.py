import logging
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg

from magpie.db.migrate import run_migrations

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, pool: asyncpg.Pool, has_vectors: bool = False):
        self._pool = pool
        self.has_vectors = has_vectors

    @classmethod
    async def connect(cls, database_url: str) -> "Database":
        pool = await asyncpg.create_pool(database_url)
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
        project_id: str | None = None,
        org_id: str | None = None,
        workspace: str | None = None,
    ) -> str:
        entry_id = uuid4().hex
        now = datetime.now(UTC)
        if embedding and self.has_vectors:
            await self._pool.execute(
                """INSERT INTO entries
                   (id, title, content, category, tags, source,
                    embedding, user_id, project_id, org_id, workspace,
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
                project_id,
                org_id,
                workspace,
                now,
                now,
            )
        else:
            await self._pool.execute(
                """INSERT INTO entries
                   (id, title, content, category, tags, source,
                    user_id, project_id, org_id, workspace,
                    created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                entry_id,
                title,
                content,
                category,
                tags or [],
                source,
                user_id,
                project_id,
                org_id,
                workspace,
                now,
                now,
            )
        return entry_id

    async def get_entry(self, entry_id: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT id, title, content, category, tags, source, user_id, project_id, org_id,"
            " workspace, created_at, updated_at FROM entries WHERE id = $1",
            entry_id,
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
        result = await self._pool.execute("DELETE FROM entries WHERE id = $1", entry_id)
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
        project_id: str | None = None,
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

        if project_id:
            idx += 1
            conditions.append(f"project_id = ${idx}")
            params.append(project_id)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        idx += 1
        offset_idx = idx
        params.append(offset)
        idx += 1
        limit_idx = idx
        params.append(limit)

        cols = ("id, title, content, category, tags, source, user_id, project_id,"
                " org_id, workspace, created_at, updated_at")
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

    async def search_semantic(
        self,
        embedding: list[float],
        user_id: str | None = None,
        org_id: str | None = None,
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
            f"SELECT id, title, content, category, tags, source,"
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
            f"SELECT id, title, content, category, tags, source,"
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

        if workspace:
            idx += 1
            conditions.append(f"workspace = ${idx}")
            params.append(workspace)

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
            f"SELECT id, title, content, category, tags, source, workspace,"
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
                            embedding, user_id, org_id, workspace,
                            created_at, updated_at)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                        new_id, title, content, category, tags or [],
                        lineage_source, str(embedding),
                        user_id, org_id, workspace, now, now,
                    )
                else:
                    await conn.execute(
                        """INSERT INTO entries
                           (id, title, content, category, tags, source,
                            user_id, org_id, workspace,
                            created_at, updated_at)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
                        new_id, title, content, category, tags or [],
                        lineage_source,
                        user_id, org_id, workspace, now, now,
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
        project_id: str | None = None,
        org_id: str | None = None,
        workspace: str | None = None,
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
            project_id=project_id,
            org_id=org_id,
            workspace=workspace,
        )
        return entry_id, False

    # -- API Keys --

    async def create_api_key(
        self,
        name: str,
        key_hash: str,
        key_prefix: str,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> str:
        key_id = uuid4().hex
        await self._pool.execute(
            "INSERT INTO api_keys (id, name, key_hash, key_prefix, user_id, org_id)"
            " VALUES ($1, $2, $3, $4, $5, $6)",
            key_id, name, key_hash, key_prefix, user_id, org_id,
        )
        return key_id

    async def get_api_key(self, key_id: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT id, name, key_prefix, user_id, org_id, created_at, last_used_at"
            " FROM api_keys WHERE id = $1",
            key_id,
        )
        return dict(row) if row else None

    async def get_api_key_by_hash(self, key_hash: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT id, name, key_prefix, user_id, org_id, created_at, last_used_at"
            " FROM api_keys WHERE key_hash = $1",
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
            "SELECT id, name, key_prefix, user_id, org_id, created_at, last_used_at"
            " FROM api_keys ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]

    async def delete_api_key(self, key_id: str) -> bool:
        result = await self._pool.execute("DELETE FROM api_keys WHERE id = $1", key_id)
        return result == "DELETE 1"

    async def list_api_keys_for_user(self, user_id: str) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT id, name, key_prefix, user_id, org_id, created_at, last_used_at"
            " FROM api_keys WHERE user_id = $1 ORDER BY created_at DESC",
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

    async def list_workspaces(self, org_id: str) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM workspaces WHERE org_id = $1 ORDER BY name", org_id
        )
        return [dict(r) for r in rows]

    async def delete_workspace(self, ws_id: str) -> bool:
        result = await self._pool.execute("DELETE FROM workspaces WHERE id = $1", ws_id)
        return result == "DELETE 1"

    # -- Email OTP --

    async def create_email_token(self, email: str, code: str, ttl_minutes: int = 10) -> str:
        token_id = uuid4().hex
        expires = datetime.now(UTC) + __import__("datetime").timedelta(minutes=ttl_minutes)
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
        expires = datetime.now(UTC) + __import__("datetime").timedelta(hours=ttl_hours)
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
