import logging
import re
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def run_migrations(pool: asyncpg.Pool) -> None:
    """Run pending SQL migrations in order."""
    async with pool.acquire() as conn:
        # Ensure migrations table exists (bootstrap)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        applied = {
            row["version"]
            for row in await conn.fetch("SELECT version FROM schema_migrations")
        }

        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        for f in migration_files:
            match = re.match(r"^(\d+)", f.name)
            if not match:
                continue
            version = int(match.group(1))
            if version in applied:
                continue

            logger.info("Applying migration %s", f.name)
            sql = f.read_text()
            try:
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES ($1, $2)",
                    version,
                    f.name,
                )
                logger.info("Applied migration %s", f.name)
            except asyncpg.exceptions.FeatureNotSupportedError:
                logger.warning(
                    "Skipping migration %s (extension not available)", f.name
                )
                await conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES ($1, $2)",
                    version,
                    f.name,
                )
