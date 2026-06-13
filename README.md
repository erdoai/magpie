# magpie

Knowledge store with semantic + keyword search. Built for AI agents, usable by humans.

Postgres + pgvector. REST API + MCP server. Management UI.

## What it does

- **Dual search** — semantic (vector embeddings) + keyword (Postgres full-text), combined with Reciprocal Rank Fusion
- **Workspaces** — organize knowledge by project (support, engineering, general, etc.)
- **Orgs + teams** — share knowledge within your team, invite members
- **MCP server** — connect AI agents (Claude Code, Cursor, etc.) via the Model Context Protocol
- **REST API** — use from any HTTP client
- **Management UI** — browse, search, edit, create, archive entries

## What it doesn't do

Not an agent framework. Not a chat memory system. Not a knowledge graph.

## Quick start

```bash
pip install magpie-ai

export DATABASE_URL=postgresql://user:pass@host:5432/magpie
export OPENAI_API_KEY=sk-...  # optional — keyword search works without it

magpie serve
```

Server starts on `http://localhost:8200`. API docs at `/docs`.

## MCP integration

### Claude Code

```bash
claude mcp add --transport http magpie https://your-magpie-server/mcp \
  --header "Authorization: Bearer YOUR_API_KEY"
```

This gives Claude Code these tools:

| Tool | Description |
|------|-------------|
| `search` | Semantic + keyword search across knowledge |
| `write` | Save knowledge (requires workspace) |
| `read` | Read entry by ID |
| `list_entries` | Browse/filter entries |
| `archive` | Archive an entry |

**Workspace pattern**: When writing knowledge, you specify which project it relates to (`workspace: "support"`, `workspace: "engineering"`, etc.). When searching, you can scope to a workspace or search across all.

### YAML-configured clients

Agents that take a YAML MCP config:

```yaml
mcp:
  magpie:
    url: https://your-magpie-server/mcp
    headers:
      Authorization: "Bearer ${MAGPIE_API_KEY}"
```

Then give agents access: `mcp_servers: [magpie]`

## Auth

Magpie supports three auth methods:

**API keys** (for agents/programmatic access):
```bash
export API_KEY=your-static-key
# Or create per-user keys via the API/UI
```

**Email OTP** (for human users):
```bash
export RESEND_API_KEY=re_...
export RESEND_FROM="magpie <hi@yourdomain.com>"
```

**Session cookies** — set after email OTP login, 30-day TTL.

When `API_KEY` is empty and `RESEND_API_KEY` is empty, auth is disabled (local dev).

## Orgs + workspaces

- **Org** = your team. Members share knowledge within the org. Roles: owner > admin > editor > viewer.
- **Workspace** = a broad app/product namespace (e.g. "support", "engineering", "general").
- **Project** = a narrower work area within a workspace (e.g. a customer or product slug). Entries, collections, and searches accept both.
- **Visibility**: you see your entries + your org's entries + global entries.

Create orgs and invite members from the Settings page in the UI.

## Collections

Named JSON document stores for structured context read whole by key: strategy, config, brand tokens, advisories, metrics. Document values are typed (`json`, `string`, `integer`, `float`, `boolean`, `datetime`) — declared on write, validated, and returned with reads so agents deserialize without guessing.

## Links

Markdown entries can reference other knowledge with `[[wikilinks]]`:

- `[[Entry Title]]` — link to another entry (resolved within your visibility)
- `[[Entry Title|display text]]`
- `[[https://example.com]]` — external URL
- `[[service:ticket:1024]]` — product resource reference (`app:type:id`)

Links are reparsed on every save. Reads return outgoing links and backlinks; unresolved titles become backlinks automatically once the target entry exists.

Entries can also embed **value references** that resolve at read time (`POST /api/entries/:id/resolve`, or `read(resolved=true)` over MCP) without mutating the stored Markdown:

- `{{config.trial_days}}` — collection value by dotted path
- `{{collection:config#trial_days}}` — explicit long form
- `{{attachment:logo-primary}}` — attachment on the current entry by role/filename

Unresolved or unauthorized references render as visible placeholders and are reported in a dependency list so agents know exactly what's missing.

## Attachments

Attachments are owned by knowledge entries — logos, screenshots, SQL snippets, briefs, PDFs. Each gets a stable `magpie:<id>` handle; small SQL/text attachments are inlined in reads, binaries get download URLs. Browser-safe images can opt into a stable public URL at `/public/assets/<id>` (never SQL/text/PDF).

Role/filename conventions give agents deterministic asset joins for brand and landing-page work:

`logo-primary`, `logo-mono-white`, `favicon-32x32`, `apple-icon-180x180`, `hero-*`, `product-*`, `customer-logo-*`, `headshot-*`, `screenshot-*`, `query-*`, `source`

Storage backends: local filesystem (default) or any S3-compatible store (AWS S3, Cloudflare R2, MinIO, Railway object storage) — see Config.

## Repo sync (bundles)

Author knowledge as a folder of files in git, then sync it to the server —
docs-as-code for knowledge. The repo is the source of truth; the server is the
search/serve index.

```bash
magpie push ./knowledge --workspace support --project billing   # repo  -> server
magpie export ./knowledge --workspace support                   # server -> repo
```

Bundle layout:

```
knowledge/
├── <entry>.md                  # markdown + strict frontmatter (entries)
├── collections/
│   ├── _manifest.json          # canonical store/key registry (anti-drift)
│   └── <slug>.json             # repo-canonical collection: { key: value }
└── index.html                  # self-contained offline viewer (written by export)
```

**Frontmatter** is a strict, versioned, *closed* schema — only these fields,
unknown keys are rejected so it never drifts into a second KV store:

```markdown
---
magpie_version: 1
category: resource        # project | area | resource | archive
title: Refund policy
tags: [policy, billing]
source: handbook
---

# Refund policy

Body markdown...
```

Entries are identified by their path in the bundle, so re-pushing updates in
place instead of duplicating.

**Collections have two layers.** Repo-canonical stores (`collections/<slug>.json`)
are curated, version-controlled, and synced by `push`; the server rejects agent/API
writes to them. Server-canonical stores are live, agent-written runtime data and
are never exported — so runtime values never end up committed to git.

**Anti-drift.** `_manifest.json` declares the canonical stores (and optionally
their keys). `push` rejects collections that aren't declared (suggesting the
nearest match) and near-duplicate slugs (`brand-tokens` vs `brand_tokens`);
the MCP server refuses to create a store that near-duplicates an existing one.

`export` also writes a zero-backend `index.html` — open it offline to browse the
bundle as a linked knowledge graph.

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/entries` | Create entry |
| `GET` | `/api/entries` | List (filter by category, tags, workspace) |
| `GET` | `/api/entries/{id}` | Get one |
| `PUT` | `/api/entries/{id}` | Update |
| `DELETE` | `/api/entries/{id}` | Delete |
| `POST` | `/api/entries/{id}/archive` | Archive |
| `POST` | `/api/search` | Dual search |
| `POST` | `/api/keys` | Create API key |
| `GET` | `/api/keys` | List keys |
| `POST` | `/api/orgs` | Create org |
| `GET` | `/api/orgs` | List your orgs |

Auth: `Authorization: Bearer <key>` header, or session cookie from email login.

## Config

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Postgres connection string | *required* |
| `OPENAI_API_KEY` | OpenAI API key for embeddings | *empty (keyword only)* |
| `API_KEY` | Static auth key | *empty (no auth)* |
| `SESSION_SECRET` | Secret for session cookies | *empty* |
| `RESEND_API_KEY` | Resend key for email OTP | *empty (API key login only)* |
| `RESEND_FROM` | Email sender address | *empty* |
| `HOST` | Server bind host | `0.0.0.0` |
| `PORT` | Server port | `8200` |
| `STORAGE_PROVIDER` | Attachment storage: `local` or `s3` | `local` |
| `STORAGE_DIR` | Local storage directory | `data/attachments` |
| `STORAGE_BUCKET` | S3 bucket name | *empty* |
| `STORAGE_ENDPOINT` | S3-compatible endpoint (R2/MinIO/Railway) | *AWS default* |
| `STORAGE_ACCESS_KEY_ID` | S3 access key | *empty* |
| `STORAGE_SECRET_ACCESS_KEY` | S3 secret key | *empty* |
| `STORAGE_REGION` | S3 region | `us-east-1` |
| `ASSET_PUBLIC_BASE_URL` | Base URL for public asset links | *empty (root-relative)* |

## Deploy

### Docker

```bash
docker build -t magpie .
docker run -e DATABASE_URL=... -p 8200:8200 magpie
```

### Railway (via scaffold)

```bash
pip install scaffold
scaffold up
```

## Development

```bash
git clone https://github.com/erdoai/magpie.git
cd magpie
pip install -e ".[dev]"
cd web && yarn install && yarn build && cd ..
magpie serve
```

## License

MIT
