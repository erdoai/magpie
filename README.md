# magpie

Knowledge store with semantic + keyword search. Built for AI agents, usable by humans.

## What it does

- **Dual search**: Semantic (vector embeddings) + keyword (Postgres full-text search), combined with Reciprocal Rank Fusion
- **PARA categories**: Organize knowledge as Projects, Areas, Resources, or Archives
- **REST API + MCP server**: Use from any HTTP client or connect AI agents via MCP
- **Management UI**: Browse, edit, search, and archive entries *(coming in v0.2)*

## What it doesn't do

- It's not an agent framework
- It's not a chat memory system
- It's not a knowledge graph
- It's not a SaaS product

## Quick start

```bash
pip install magpie-ai

# Set your Postgres URL (needs pgvector extension)
export MAGPIE_DATABASE_URL=postgresql://user:pass@host:5432/magpie

# Optional: enable semantic search
export MAGPIE_OPENAI_API_KEY=sk-...

# Start
magpie serve
```

Server starts on `http://localhost:8200`. API docs at `/docs`.

## Usage

### REST API

```bash
# Create an entry
curl -X POST http://localhost:8200/api/entries \
  -H 'Content-Type: application/json' \
  -d '{"title": "Deploy process", "content": "Run scaffold up to deploy to Railway", "category": "resource", "tags": ["deploy", "railway"]}'

# Search
curl -X POST http://localhost:8200/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "how to deploy"}'

# List entries
curl http://localhost:8200/api/entries

# Archive
curl -X POST http://localhost:8200/api/entries/{id}/archive
```

### MCP (for AI agents)

Connect any MCP-compatible agent to `http://localhost:8200/mcp`. Available tools:

| Tool | Description |
|------|-------------|
| `magpie_search` | Search entries (semantic + keyword) |
| `magpie_write` | Create a new entry |
| `magpie_read` | Read entry by ID |
| `magpie_list` | List entries with filters |
| `magpie_archive` | Archive an entry |

#### Claude Code

Add to your `.claude/settings.json`:

```json
{
  "mcpServers": {
    "magpie": {
      "url": "http://localhost:8200/mcp"
    }
  }
}
```

#### Crow

Add to your `crow.yml`:

```yaml
mcp:
  magpie:
    url: http://localhost:8200/mcp
```

Then give agents access: `mcp_servers: [magpie]`

## Auth

Set `MAGPIE_API_KEY` to enable bearer token auth:

```bash
export MAGPIE_API_KEY=my-secret-key

# Then pass it in requests:
curl -H 'Authorization: Bearer my-secret-key' http://localhost:8200/api/entries
```

When unset, all endpoints are open (good for local dev).

## Config

| Variable | Description | Default |
|----------|-------------|---------|
| `MAGPIE_DATABASE_URL` | Postgres connection string | *required* |
| `MAGPIE_OPENAI_API_KEY` | OpenAI API key for embeddings | *empty (keyword only)* |
| `MAGPIE_EMBEDDING_MODEL` | Embedding model name | `text-embedding-3-small` |
| `MAGPIE_API_KEY` | Static auth key | *empty (no auth)* |
| `MAGPIE_HOST` | Server bind host | `0.0.0.0` |
| `MAGPIE_PORT` | Server port | `8200` |

## Deployment

### Docker

```bash
docker build -t magpie .
docker run -e MAGPIE_DATABASE_URL=... -p 8200:8200 magpie
```

### Railway

Deploy with [scaffold](https://github.com/erdoai/scaffold):

```bash
scaffold up
```

## Development

```bash
git clone https://github.com/erdoai/magpie.git
cd magpie
pip install -e ".[dev]"
magpie serve
ruff check .
pytest
```

## License

MIT
