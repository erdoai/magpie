# magpie

Knowledge store with semantic + keyword search. Built for AI agents, usable by humans.

Postgres + pgvector. REST API + MCP server. Management UI.

## What it does

- **Dual search** — semantic (vector embeddings) + keyword (Postgres full-text), combined with Reciprocal Rank Fusion
- **Workspaces** — organize knowledge by project (devbot, crow, general, etc.)
- **Orgs + teams** — share knowledge within your team, invite members
- **MCP server** — connect AI agents (Claude Code, Crow, etc.) via the Model Context Protocol
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

**Workspace pattern**: When writing knowledge, you specify which project it relates to (`workspace: "devbot"`, `workspace: "crow"`, etc.). When searching, you can scope to a workspace or search across all.

### Crow

Add to `crow.yml`:

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

- **Org** = your team. Members share knowledge within the org.
- **Workspace** = a project scope (e.g. "devbot", "crow", "general"). Used in tool calls to organize knowledge.
- **Visibility**: you see your entries + your org's entries + global entries.

Create orgs and invite members from the Settings page in the UI.

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
