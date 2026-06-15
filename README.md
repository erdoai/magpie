# magpie

One source of truth your agents and team keep true. Define a value, a metric, a definition once — reference it anywhere, and it resolves to the one canonical value at read time, so your docs, your metrics, and your AI never disagree.

The consistency layer for agent and human knowledge: durable Markdown and typed KV stores in one store, with dual semantic + keyword search and dedupe/merge that stop contradictory copies forming. Postgres + pgvector. REST API + MCP server + CLI + management UI — one product, same rules across every surface.

📚 **Documentation:** [Introduction](docs/site/introduction.mdx) ·
[Quickstart](docs/site/quickstart.mdx) ·
[Self-hosting](docs/site/self-hosting.mdx) ·
[CLI](docs/site/cli/commands.mdx) ·
[MCP](docs/site/mcp/overview.mdx) ·
[REST API](docs/site/reference/api.mdx)

## What it does

- **Dual search** — semantic (vector embeddings) + keyword (Postgres full-text), fused with Reciprocal Rank Fusion. Works keyword-only without an embedding key.
- **Typed KV stores** — named typed key/value stores for structured context (config, brand tokens, metrics), read whole by key and returned typed.
- **Links & references** — `[[wikilinks]]` with backlinks, and `{{kv.key}}` / `{{attachment:…}}` references that resolve to live values at read time.
- **Attachments** — files owned by entries (logos, screenshots, SQL, briefs) with stable `magpie:<id>` handles.
- **Stays coherent** — dedupe-on-write, semantic duplicate detection, merge, and a KV-store registry keep the store from fragmenting. See [Staying coherent](docs/site/concepts/coherence.mdx).
- **History** — a durable activity log (what changed, when, by whom) that survives overwrites and deletes, plus previous versions of every entry and KV key. See [Activity log](docs/site/concepts/activity.mdx).
- **Orgs + teams** — share within an org with roles (owner > admin > editor > viewer); fail-closed visibility.
- **Every surface** — [REST API](docs/site/reference/api.mdx), [MCP server](docs/site/mcp/overview.mdx), [CLI](docs/site/cli/commands.mdx), and a management UI.

**What it isn't:** not an agent framework, not a chat-memory system, not a knowledge graph.

## Quick start

**Self-host with Docker Compose** (Postgres + pgvector + server, one command):

```bash
docker compose up --build      # → http://localhost:8200  (REST + MCP + UI)
```

**Or with pip and your own Postgres:**

```bash
pip install erdo-magpie

export DATABASE_URL=postgresql://user:pass@host:5432/magpie
export OPENAI_API_KEY=sk-...          # optional — keyword search works without it

magpie migrate                        # apply schema (serve does NOT auto-migrate)
magpie serve                          # → http://localhost:8200
```

**Or deploy to Railway:** the repo ships a `railway.json` — deploy the repo, add a pgvector Postgres, set `DATABASE_URL`, done. See [Deploy to Railway](docs/site/self-hosting.mdx#deploy-to-railway).

See the [Self-hosting guide](docs/site/self-hosting.mdx) for storage, auth, backups, and production notes.

## Connect an agent (MCP)

```bash
# Hosted server over OAuth
claude mcp add --transport http magpie https://your-magpie-server/mcp

# …or a local stdio proxy via the CLI
claude mcp add magpie -- npx @erdo/magpie mcp
```

That exposes Magpie's full tool set (identical on the remote server and the stdio proxy):

| Area | Tools |
|------|-------|
| Knowledge | `search`, `read`, `write`, `list_entries`, `archive` |
| Coherence | `find_duplicates`, `merge` (and `write` with `dedupe`) |
| Links & references | `list_links`, `resolve_knowledge` |
| KV | `kv_list`, `kv_get`, `kv_set`, `kv_delete`, `kv_history` |
| Attachments | `upload_attachment`, `list_attachments`, `get_attachment` |
| History | `list_updates`, `entry_history` |

Full reference: [MCP tools](docs/site/mcp/tools.mdx) · setup for other clients: [MCP setup](docs/site/mcp/setup.mdx).

## CLI

The user-facing CLI (`@erdo/magpie`) is a thin client over the REST API:

```bash
npx @erdo/magpie login --api-url https://your-magpie-server
magpie write --title "Refund policy" --file refund-policy.md
magpie search "incident runbook"
magpie read <entry-id> --resolved
```

Full command reference: [CLI](docs/site/cli/commands.mdx).

## Repo sync

Author knowledge as a folder of Markdown + JSON in git, then sync it — docs-as-code for knowledge. The repo is the source of truth; the server is the search/serve index, with a manifest that guards against drift.

```bash
magpie push ./knowledge --workspace support     # repo  → server
magpie export ./knowledge --workspace support    # server → repo (+ offline viewer)
```

See [Repo sync](docs/site/repo-sync/overview.mdx), [frontmatter spec](docs/site/repo-sync/frontmatter.mdx), and [anti-drift](docs/site/repo-sync/anti-drift.mdx).

## Configuration

Configured by environment variables (no prefix). The essentials:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Postgres connection string | **required** |
| `OPENAI_API_KEY` | Enables semantic search | *empty (keyword only)* |
| `SESSION_SECRET` | Secret for session cookies | *empty* |
| `STORAGE_PROVIDER` | Attachment storage: `local` or `s3` | `local` |

Full list (storage, email login, OAuth): [Configuration](docs/site/reference/configuration.mdx). Auth methods (API keys, email OTP, OAuth): [Authentication](docs/site/reference/auth.mdx).

## Development

```bash
git clone https://github.com/erdoai/magpie.git
cd magpie
pip install -e ".[dev]"
ruff check . && pytest

# Web UI (served by the server in production)
cd web && yarn install && yarn build
```

See [`CLAUDE.md`](CLAUDE.md) for architecture, the surface-parity rule, and key patterns.

## License

MIT
