# magpie

Knowledge store with semantic + keyword search. Postgres + pgvector.

## Architecture

Single FastAPI server exposing:
- **REST API** at `/api/` — CRUD + search for knowledge entries
- **MCP server** at `/mcp` — 18 tools for AI agents (search/read/write/list/archive,
  find_duplicates/merge, bulk_edit, list_updates, list_links/resolve_knowledge,
  kv list/get/set/delete, attachment upload/list/get) — kept in lockstep across
  both MCP servers

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
magpie push ./bundle      # sync a knowledge bundle (repo -> server)
magpie export ./bundle    # write entries + repo kv stores to a bundle (server -> repo)
magpie import markdown .  # import foreign markdown/claude memories
magpie rescope --workspace reach --to-workspace erdo --apply  # bulk-move entries
magpie retag --workspace reach --rename old=new --apply       # bulk add/remove/rename tags
magpie version            # show version
```

(Server-side ops against the DB. The user-facing `@erdo/magpie` in `cli/` is a thin
REST client with the same `push`/`export` plus `search`/`read`/`write`/etc.)

## Config

Environment variables, **no prefix** (`Settings` uses `env_prefix=""`):
- `DATABASE_URL` — Postgres connection string (required)
- `OPENAI_API_KEY` — for embeddings (optional, keyword search works without)
- `API_KEY` — static auth key (optional, empty = no auth). **Unrestricted /
  single-tenant**: a request bearing it bypasses org isolation. Don't set it on
  a multi-tenant instance — use per-user keys / session login instead.
- `PORT` — server port (default: 8200)

Full list in `magpie/config/settings.py` and `docs/site/reference/configuration.mdx`.

## Data model

Entries are plain notes with an `archived_at` lifecycle status (NULL = active).
Scoped by user_id, org_id, workspace, project (all optional, NULL = global).
Workspace = broad app/product namespace (e.g. "reach"); project = narrower work
area within it (e.g. "alertee"). Org roles: owner > admin > editor > viewer.

**Org is the only enforced boundary** (membership + roles). Workspace/project
are filter tags within a trusted org, not security boundaries. A user can belong
to many orgs but acts in one **active org** at a time, resolved as:
`X-Organization-ID` header (membership-validated, 403 if not a member) > saved
`users.default_org_id` (via `POST /api/orgs/{id}/select`) > first membership.
Shared resolver: `context.resolve_active_org()`. A user token can switch among
the user's orgs via the header, capped by the token's role (`context.cap_role`).

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

## Code style

- All imports go at the top of the file. No function-level/local imports, no
  `__import__` tricks — this applies to CLI commands, lifespans, and routes too.

## Key patterns

- Embedding provider is abstracted (`magpie/embeddings/base.py`). OpenAI is default.
- Search fusion in `magpie/search/fusion.py` — runs semantic + keyword in parallel, merges with RRF.
- Migration runner copied from crow pattern — numbered SQL files in `magpie/db/migrations/`.
- MCP tools initialized with db + embedder at startup via `init_mcp()`.
- **Fail-closed reads**: `db.get_entry/get_kv_store/get_kv_pair` filter
  visibility in SQL. Pass `**ctx.view_filter` (REST + both MCP servers) or
  `trusted=True` for server-internal reads (links, resolve, CLI, post-write
  round-trips). No scope + not trusted ⇒ only global rows. Don't add a raw
  by-id read that bypasses this.
- **Activity log** (`magpie/activity.py` + `db.record_activity`/`list_activity`,
  `activity_events` table): append-only event spine behind `/api/updates`. Both
  write surfaces call the shared `activity.*` emit helpers — REST routes AND the
  hosted MCP server (which writes the DB directly, so it can't inherit emission
  from routes); bulk emits once inside shared `run_bulk`. Emission is
  best-effort (record_activity swallows+logs its own errors — never fails a
  committed write). Actor (`user`/`token`/`system`) comes from `ctx.actor`.
  Add a new event type to `activity.py`, never inline a raw `record_activity`.
- **Bulk rescope/retag** (`magpie/bulk.py` + `db.bulk_update_entries`): in-place
  transactional UPDATE — preserves ids/links/embeddings (never copy-delete).
  `match` is required (never the whole store); writes are confined to own +
  active-org rows, never global. Dry-run is the default; applying needs `admin`.
  Shared `build_match`/`build_changes`/`run_bulk` back REST `POST /api/entries/bulk`,
  the `bulk_edit` MCP tool, and both CLIs' `rescope`/`retag`.

## CLI / MCP / API / Docs parity

**The surfaces are one product — keep them in lockstep.** When you change a tool,
command, or user-facing capability, update every surface it belongs on **in the
same change**:

- **REST API** (`magpie/server/routes/*`) — the source of truth. Business logic,
  validation, role/visibility checks, and anti-drift guards live here (and in the
  shared `magpie/sync.py` / `magpie/bundle.py` / `magpie/export.py` helpers), once.
  Clients are thin.
- **Both MCP servers** must expose the same agent tool set: the remote/hosted
  server (`magpie/mcp/server.py`) and the local stdio proxy (`cli/src/mcp.ts`).
  The stdio server proxies REST, so server-side guards apply automatically — but a
  new *tool* must be added to both.
- **Both CLIs**: the Python `magpie` CLI (`magpie/cli/main.py`) is for
  server/self-hosted ops against the DB (`serve`, `migrate`, `import`, `push`,
  `export`, attachments); the TypeScript `@erdo/magpie` (`cli/src/`) is the
  user-facing client over REST. A capability that suits both belongs on both.
  Logic stays server-side — clients read/write files and call the API.
- **Docs** (`docs/site/`, Mintlify): add/update the reference page in the same
  change — a user-facing feature isn't done until it's documented. New page →
  also add it to `docs/site/docs.json` nav. Don't pin CLI/API versions in prose.
  **The Mintlify content root must stay `docs/site/`** so `docs/plans/` (internal
  strategy) can never be published.

Shipping a capability on only one surface (CLI without docs, a guard in the remote
MCP but not REST, a tool in one MCP server but not the other) is incomplete —
finish the whole surface. Keep this file and `AGENTS.md` in sync.
