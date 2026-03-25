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
