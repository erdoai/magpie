# magpie

Knowledge store with semantic + keyword search. Postgres + pgvector.

## Architecture

Single FastAPI server exposing:
- **REST API** at `/api/` — CRUD + search for knowledge entries
- **MCP server** at `/mcp` — 5 tools for AI agents (search, write, read, list, archive)

Storage: Postgres with pgvector for embeddings and tsvector for full-text search.
Search: Reciprocal Rank Fusion combining semantic (vector similarity) and keyword (full-text) results.

## Tech stack

- Python 3.11+, async-first
- FastAPI + uvicorn (server)
- asyncpg + pgvector (database)
- httpx (embedding API calls)
- MCP SDK (MCP server)
- Pydantic + pydantic-settings (models/config)
- Typer + Rich (CLI)

## Commands

```bash
magpie serve              # start server on :8200
magpie migrate            # run migrations only
magpie version            # show version
```

## Config

Environment variables with `MAGPIE_` prefix:
- `MAGPIE_DATABASE_URL` — Postgres connection string (required)
- `MAGPIE_OPENAI_API_KEY` — for embeddings (optional, keyword search works without)
- `MAGPIE_API_KEY` — static auth key (optional, empty = no auth)
- `MAGPIE_PORT` — server port (default: 8200)

## Data model

Entries use PARA categories (Projects / Areas / Resources / Archives).
Scoped by user_id, project_id, org_id (all optional, NULL = global).

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

## Key patterns

- Embedding provider is abstracted (`magpie/embeddings/base.py`). OpenAI is default.
- Search fusion in `magpie/search/fusion.py` — runs semantic + keyword in parallel, merges with RRF.
- Migration runner copied from crow pattern — numbered SQL files in `magpie/db/migrations/`.
- MCP tools initialized with db + embedder at startup via `init_mcp()`.
