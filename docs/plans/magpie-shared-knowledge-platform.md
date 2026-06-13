# Magpie Shared Knowledge Platform

Date: 2026-06-12
Status: in progress

## Progress

Keep this section current as work lands. Update it in the same change as the work itself.

- [x] Phase 0: Product contract — plan written, README repositioned. CLI decision: TypeScript user CLI + Python server CLI.
- [x] Phase 1: Tenancy and scoping — landed 2026-06-12
  - [x] Migration 007: `entries.project_id` → `project`, scoped API keys (workspace/project/role), org roles normalized to owner/admin/editor/viewer
  - [x] `AuthContext` (`magpie/server/context.py`): role hierarchy, entry visibility rules, key-scope clamping. Role checks on all REST write paths; org-visibility checks on entry get/update/delete/archive (previously unscoped — any caller could touch any entry by ID). Keys bound to caller, listed per-user, no role escalation. Org member/workspace management gated by admin/editor roles.
  - [x] workspace/project filters threaded through DB search + RRF fusion (two bugs fixed: REST search accepted `workspace` but dropped it; MCP search post-filtered on a column the query didn't select, so workspace-filtered MCP searches returned nothing)
  - [x] MCP tools scoped by OAuth token user/org (previously unscoped) + `project` param on search/write/list/find_duplicates/merge
  - [x] Visibility/cross-org isolation tests (`tests/test_isolation.py`, 16 tests over real routers + auth middleware with an in-memory DB)
  - [x] UI project filters/badges + CLI `--project` on import
  - Note: session auth still resolves "first org" as the active org; proper org switching is deferred to hosted onboarding (Phase 7). MCP tools apply the token user's org role; workspace-pinned API keys do not yet apply to MCP (OAuth tokens are user-level).
- [x] Phase 2: Links — landed 2026-06-12
  - [x] Migration 008: `links` table (polymorphic source/target for Phase 3 reuse; org_id mirrors source entry, NULL = global)
  - [x] Parser (`magpie/links.py`): `[[Title]]`, `[[Title|display]]`, `[[https://url]]`, `[[app:type:id]]` resource refs; code blocks skipped; deduped by normalized target
  - [x] Link sync on every write path (REST create/update/merge, MCP write/merge, CLI import). Title links resolve within writer's visibility (org/global); unresolved links stored and matched as backlinks by normalized title once the target exists. Deleting an entry drops its outgoing links and demotes inbound links to unresolved.
  - [x] `GET /api/entries/:id/links` (outgoing + visibility-filtered backlinks), MCP `list_links` tool, link/backlink sections in MCP `read`
  - [x] UI links/backlinks panel on the entry page
  - [x] 11 parser + link-behavior tests, incl. cross-org resolution/backlink leak checks
- [x] Phase 3: Collections — landed 2026-06-12
  - [x] Migration 009: collections (org/workspace/project/slug unique via coalesced index) + documents (collection+key unique, JSONB value, `value_type`)
  - [x] Typed values (`magpie/collections.py`): json/string/integer/float/boolean/datetime, validated on write, returned with reads; bools rejected as ints, datetimes must be ISO 8601
  - [x] JSONB codec on the asyncpg pool (values are Python objects, not strings)
  - [x] REST CRUD: GET/POST/DELETE `/api/collections`, GET/PUT/DELETE `/api/collections/:slug/documents[/:key]` with editor role checks, org visibility, key-scope clamping
  - [x] MCP tools: `list_collections`, `get_document`, `set_document` (with `create_collection` flag + missing-key hints), `delete_document`
  - [x] UI collections browser: sidebar list, document table with type badges, JSON/typed editor
  - [x] 10 collection tests (typed validation, roundtrip, cross-org isolation, role checks, scoped-key clamping); suite at 60
  - Note: collection/document wikilink *targets* deferred to Phase 5 (reference resolution), where `{{collection...}}` syntax lands; the links table is already polymorphic.
- [x] Phase 4: Attachments — landed 2026-06-12
  - [x] Storage abstraction: local filesystem + S3-compatible (AWS/R2/MinIO/Railway) via httpx + SigV4, presigned GET URLs, no boto3 dependency
  - [x] Migration 010: entry-owned attachments (kind/role/filename/media_type, attachment-level `public` flag). Note: dropped `storage_bucket` column from the original schema — single bucket per deployment, configured in env.
  - [x] REST: multipart upload, metadata read (inline `content_text` for small SQL/text), download (signed-URL redirect or stream), delete (blob + row), `GET /public/assets/:id` for explicitly-public browser-safe images only
  - [x] Stable `magpie:<id>` handles; public URLs root-relative (or `ASSET_PUBLIC_BASE_URL`) so generated pages don't embed expiring signed URLs
  - [x] MCP: `upload_attachment` (base64), `list_attachments`, `get_attachment`; attachments listed in `read`
  - [x] CLI: `magpie attachments add/list`
  - [x] UI attachments panel: upload with role, previews, copy handle/public URL, delete
  - [x] Role/filename conventions documented in README + MCP tool prompts
  - [x] 11 attachment tests (storage roundtrip, traversal rejection, upload/read/delete, public gating, cross-org isolation); suite at 71
  - Decision (open question resolved): public serving is **attachment-level opt-in** (`public=true` at upload, images only) — simplest and most explicit.
- [x] Phase 5: Reference resolution — landed 2026-06-12
  - [x] Resolver (`magpie/resolve.py`): `{{shorthand.collection.paths}}` (longest slug prefix wins), `{{collection:slug/key#json.path}}`, `{{attachment:role-or-filename}}`, `[[wikilinks]]` → Markdown links. Read-time only; stored Markdown never mutated; code blocks protected.
  - [x] Permission checks per target; unresolved/unauthorized render as `⟦unresolved: ref⟧` placeholders + status in the dependency list (resolved/not_found/unauthorized/invalid with detail)
  - [x] `POST /api/entries/:id/resolve` → `{markdown, dependencies}`
  - [x] MCP `resolve_knowledge` tool + `read(resolved=true)`
  - [x] 9 resolver tests (shorthand/explicit/scalar/JSON-path, cross-org denial, attachment refs, code-block protection); suite at 80
- [x] Phase 6: CLI — landed 2026-06-12 (not yet published to npm)
  - [x] `cli/` TypeScript workspace, `@magpie/cli`, Node 18+ (commander + MCP SDK + zod 4, native fetch)
  - [x] `login` (email OTP → mints an API key via the session, stored in `~/.config/magpie/config.json`), `logout`, `whoami`, `link` (default workspace/project)
  - [x] `org list`, `workspace list`, `search`, `read --resolved`, `write`, `archive`, `collections list/get/set`, `attachments add/list`, `import <dir>`
  - [x] `magpie mcp` — stdio MCP server proxying to the REST API with the stored key (search/read/write/list/archive/resolve_knowledge/get_document/set_document/list_attachments/get_attachment), for local agent setups
  - [ ] Publish to npm (`@magpie/cli` vs `@magpieai/cli` still open — scope availability to check at publish time)
- [~] Phase 7: Hosted deployment — core deployed 2026-06-12, hardening open
  - [x] Railway project `magpie` on Niall's personal workspace (standalone, not erdo): Postgres 18 + pgvector (EU), `server` service from repo Dockerfile
  - [x] Storage: Cloudflare R2 bucket `magpie-attachments` (WEUR) via the S3 provider, region `auto`. Note: brand-new R2 account hostnames return TLS handshake failures (alert 40) until Cloudflare provisions edge certs — resolves itself within ~30 min.
  - [x] Env: DATABASE_URL ref, generated API_KEY/SESSION_SECRET, STORAGE_*, OAUTH_ISSUER_URL + ASSET_PUBLIC_BASE_URL = https://server-production-ee91.up.railway.app
  - [x] MCP transport allowed-hosts now derived from OAUTH_ISSUER_URL + MCP_ALLOWED_HOSTS (was hardcoded to magpie.erdo.ai)
  - [x] Migrations 001–010 applied clean on fresh DB; pgvector detected; smoke-tested: entry create/search, attachment upload→R2 (inline SQL read-back), delete cleans blob, /mcp serves OAuth challenge
  - [ ] OPENAI_API_KEY not set — keyword search only until provided
  - [ ] Custom domain (currently Railway-generated; magpie.erdo.ai optional later — requires updating OAUTH_ISSUER_URL/ASSET_PUBLIC_BASE_URL)
  - [ ] Backups, per-org quotas, usage page, hosted onboarding docs, import/export path
- [ ] Phase 8: App integrations
- [~] Phase 9: Repo sync, format spec, and viewer — see design section below
  - [x] Magpie's own strict versioned closed frontmatter spec (`magpie/frontmatter.py`, 14 tests) — `magpie_version`+`category` required, closed field set, unknown keys rejected
  - [x] One-way `push` from a folder (repo = source of truth). `magpie/bundle.py` scanner (8 tests) + migration 011 `source_path` (path-as-identity) + `db.upsert_entry_by_path` + `magpie push`
  - [x] Two collection layers: repo-canonical vs server-canonical (live), source-of-truth flag. Migration 012 `collections.source`; `infer_value_type`; `scan_collections` (flat `{key:value}` JSON, types inferred); push syncs repo collections with server-conflict pre-check; write-guard rejects agent/API writes to repo-canonical stores (REST + MCP set/delete). 7 scan tests
  - [x] Manifest/catalog + anti-drift checks. `magpie/manifest.py` (9 tests): `collections/_manifest.json` registry; push rejects undeclared collections (nearest-match suggestion) + near-duplicate slugs (normalized), warns on undeclared keys; MCP create-collection rejects near-duplicate of an existing store
  - [x] Export bundle. `magpie/export.py` (9 tests, round-trips through the scanner) + `magpie export`: entries → md+frontmatter (re-using source_path), repo collections → JSON, generated `_manifest.json`. Live stores excluded. Closes the Phase 7 lock-in TODO. (Attachment binaries + sidecars: follow-up)
  - [ ] Static zero-backend HTML viewer for an exported bundle
  - [ ] (Optional, later) OKF export as a 1-line compatibility footnote if it ever gets adoption

## Summary

Turn Magpie from a lightweight searchable memory service into the shared knowledge substrate for agents, teams, and products.

Magpie should own reusable context: prose knowledge, structured JSON collections, links/backlinks, attachments, provenance, search, and agent access. Product apps such as Reach and Alertee should keep their operational databases, but stop rebuilding their own memory/search/context layers.

The product shape is:

- Hosted Magpie Cloud for low-friction use by teams and internal Erdo projects.
- Self-hosted Magpie for OSS users who want their own Postgres/object-storage deployment.
- CLI + MCP as first-class surfaces, following the Alertee pattern.
- App adapters so Reach, Alertee, Erdo, and future projects can use Magpie without copying schema or agent tools.

## Why Magpie Is Not Used Enough Today

Manual storage inside Reach and Alertee was faster because the current user, org, project, domain objects, and UI state are already local. Writing `strategicMemory` into a workspace JSON blob or Alertee quiet-period knowledge into a domain table avoids cross-service auth, deployment config, and general-purpose modeling.

That was the correct early move, but it creates a recurring tax:

- Each app rebuilds knowledge CRUD, search, and filtering.
- Each app invents its own shape for memory, context runs, notes, diagnosis, and provenance.
- Agents get one-off MCP tools per product instead of a common memory interface.
- Cross-product learning is hard because there is no shared identity for "this is reusable context".
- Attachments such as logos, screenshots, SQL snippets, brand assets, and reference images stay trapped in product-specific storage.

Magpie becomes worth using when it is not just "notes with embeddings", but the dependable substrate an app can delegate memory to.

## Product Boundary

Magpie should own:

- Durable prose knowledge in Markdown.
- Typed metadata and provenance for knowledge entries.
- Named JSON document collections.
- Links between entries, documents, and external resources.
- Attachments owned by knowledge entries.
- Semantic + keyword search.
- Permission-aware context resolution for agents.
- REST, CLI, and MCP access.

Magpie should not own:

- Product runtime state such as Reach jobs, Alertee checks, Erdo artifacts, billing, alerts, or analytics connections.
- High-volume analytical/event data.
- Workflow execution.
- Product-specific business rules.

Rule of thumb:

- If the app needs it to run, keep it local.
- If future agents or teammates should remember, search, cite, reuse, or link it, put it in Magpie.

## Core Concepts

### Organizations

An organization is the team/account boundary. Hosted Magpie requires orgs from day one; self-hosted Magpie can run with auth disabled locally but should still store an implicit org internally.

Required behavior:

- Users can belong to multiple orgs.
- API keys and OAuth tokens are scoped to an org and optional project/workspace.
- Org roles: owner, admin, editor, viewer.
- All write APIs check membership and role.

### Workspaces And Projects

Magpie already has `workspace`; keep it but make the semantics explicit.

- `workspace`: broad product/app namespace, such as `reach`, `alertee`, `erdo`, `personal`, or `customer-research`.
- `project`: narrower scoped work area, such as a Reach product, an Alertee customer org, or an Erdo customer.

The API should accept both:

```json
{
  "workspace": "reach",
  "project": "alertee"
}
```

This lets Reach write "strategy memory for the Alertee project" while Alertee writes "incident diagnosis for this customer/check" without conflicting.

### Knowledge Entries

Entries are Markdown objects with typed metadata.

Keep the existing `entries` table but evolve it toward:

- `id`
- `org_id`
- `workspace`
- `project`
- `type`: memory, decision, runbook, brand_style, strategy, diagnosis, source_note, skill, generic
- `title`
- `content_markdown`
- `summary`
- `tags`
- `source`
- `status`: active, archived, deprecated
- `metadata_json`
- `created_by_user_id`
- `created_at`, `updated_at`
- `search_vector`, `embedding`

Do not create separate tables for every semantic object unless the object is operational runtime state. The typed entry plus metadata should be enough for most reusable context.

### Links And Backlinks

Magpie should parse `[[wikilinks]]` from Markdown and store durable relational edges.

Link targets:

- Knowledge entry.
- Collection.
- Collection document.
- External URL.
- Product resource reference such as `alertee:check:<id>` or `reach:run:<id>`.

Suggested table:

```sql
CREATE TABLE links (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT,
  target_ref TEXT,
  link_text TEXT NOT NULL,
  normalized_target TEXT NOT NULL,
  metadata_json JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Behavior:

- Save/update of an entry reparses Markdown and upserts outgoing links.
- Read returns outgoing links and backlinks.
- Unresolved links remain useful and clickable/searchable.
- Agents should receive link/backlink summaries in `read_knowledge`.

### Collections

Collections are named JSON document stores. They are for structured context that should be read whole by key, not for row analytics.

Examples:

- `reach.strategy`
- `reach.brand_assets`
- `alertee.check_advisories`
- `alertee.incident_patterns`
- `erdo.customer_profiles`
- `landing_page.assets`

Suggested tables:

```sql
CREATE TABLE collections (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  workspace TEXT,
  project TEXT,
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  visibility TEXT NOT NULL DEFAULT 'org',
  created_by_user_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (org_id, workspace, project, slug)
);

CREATE TABLE documents (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  value JSONB NOT NULL,
  value_type TEXT NOT NULL DEFAULT 'json', -- json, string, integer, float, boolean, datetime
  summary TEXT,
  metadata_json JSONB NOT NULL DEFAULT '{}',
  created_by_user_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (collection_id, key)
);
```

Typed values:

Documents are key/value, and the value is not always a JSON object — it can be a scalar: string, integer, float, boolean, or datetime. Each document declares its type in `value_type`:

- Storage stays JSONB for every type (scalars stored as JSON scalars; datetimes as ISO 8601 strings with `value_type = 'datetime'`).
- Writes validate the value against the declared type and reject mismatches with a structured error.
- Reads (REST/MCP/CLI) return the value plus `value_type` so agents and adapters can deserialize without guessing — e.g. `{{reach.metrics.alertee.mrr}}` resolves to a number, not a string.
- `value_type = 'json'` is the default and covers objects/arrays.

Decision rule:

- Use a collection document for small JSON objects or typed scalars: strategy, config, brand tokens, resolved facts, preferences, advisories, metrics snapshots.
- Use the app database for operational state.
- Use an analytical warehouse/table outside Magpie for high-volume rows.

### Inline References

Markdown should support links and value references.

Proposed syntax:

- `[[Alertee positioning]]` for semantic links.
- `{{reach.strategy.alertee.positioning.wedge}}` for resolved collection/document values.
- `{{collection:reach.strategy/alertee#positioning.wedge}}` as the explicit long form.
- `{{attachment:logo-primary}}` for an attachment on the current entry by filename/role.

Resolution rules:

- Resolution happens at read/context time, not by mutating the stored Markdown.
- Permission checks apply to every target.
- Unresolved or unauthorized references return a structured placeholder to agents and a visible unresolved state in the UI.
- Agent context can request `resolved=true` to receive rendered Markdown plus a dependency list.

## Attachments

Attachments should be first-class in Magpie. This is one of the highest-leverage pieces from Erdo Knowledge.

Use cases:

- Logos, favicons, brand imagery, product screenshots, headshots, and reference images for landing pages.
- SQL snippets and deterministic query fragments.
- Text files, policies, briefs, transcripts, source documents, and runbooks.
- PDFs and source files for retrieval and provenance.
- Generated assets that future agents should reuse instead of recreating.

Key principle:

Attachments are owned by a knowledge entry. They are not random files in a bucket, and they are not just URLs embedded in Markdown.

Suggested table:

```sql
CREATE TABLE attachments (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, -- image, sql, text, pdf, file
  filename TEXT NOT NULL,
  media_type TEXT NOT NULL,
  storage_bucket TEXT NOT NULL,
  storage_key TEXT NOT NULL,
  byte_size BIGINT NOT NULL,
  description TEXT,
  role TEXT, -- logo-primary, favicon-32x32, hero, product, screenshot, query, source
  metadata_json JSONB NOT NULL DEFAULT '{}',
  created_by_user_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Agent-facing behavior:

- `read_knowledge` returns `attachments[]`.
- Each attachment has a stable handle: `magpie:<attachment_id>`.
- SQL/text attachments below an inline limit return `content_text`.
- Images/files return signed download URLs for private access.
- Browser-safe media can also expose a stable public/asset URL when the entry/project explicitly allows public serving.
- Attachments are searchable by filename, role, description, media type, and parent entry.

Public asset serving:

- Self-hosted: serve via `/public/assets/:attachment_id` only for allowlisted browser-safe media.
- Hosted: same route, backed by S3/R2/Railway object storage.
- Never expose SQL/text/PDF/document attachments through the public route.
- Public URLs must be stable and root-relative where possible so generated pages do not embed expiring signed URLs.

Filename/role conventions matter. For brand and landing-page workflows, adopt Erdo's successful pattern:

- `logo-primary`
- `logo-mono-white`
- `favicon-32x32`
- `apple-icon-180x180`
- `hero-*`
- `product-*`
- `customer-logo-*`
- `headshot-*`
- `screenshot-*`
- `query-*`

This gives agents deterministic joins: they can ask for the brand style entry, inspect attachments, and use real assets instead of guessing, hotlinking customer CDNs, or generating fake logos.

## REST API

Keep the existing REST API and add:

- `POST /api/search`
- `POST /api/entries`
- `GET /api/entries`
- `GET /api/entries/:id`
- `PUT /api/entries/:id`
- `DELETE /api/entries/:id`
- `GET /api/entries/:id/links`
- `POST /api/entries/:id/resolve`
- `POST /api/entries/:id/attachments`
- `GET /api/attachments/:id`
- `DELETE /api/attachments/:id`
- `GET /public/assets/:id`
- `GET /api/collections`
- `POST /api/collections`
- `GET /api/collections/:slug/documents`
- `GET /api/collections/:slug/documents/:key`
- `PUT /api/collections/:slug/documents/:key`
- `DELETE /api/collections/:slug/documents/:key`

All endpoints must accept `workspace` and `project` where relevant.

## MCP Surface

Magpie already has an MCP server. It should become the canonical agent memory interface.

Tools:

- `search_knowledge`
- `read_knowledge`
- `write_knowledge`
- `update_knowledge`
- `archive_knowledge`
- `list_links`
- `resolve_knowledge`
- `list_collections`
- `get_document`
- `set_document`
- `delete_document`
- `upload_attachment`
- `list_attachments`
- `get_attachment`
- `link_resource`

MCP behavior:

- Tools must take `workspace` and `project` filters.
- Tokens determine org; agents should not pass org IDs unless using multi-org hosted auth.
- `read_knowledge` should include links, backlinks, attachment summaries, and optionally resolved references.
- Attachment handles should be valid input to downstream media/file tooling.
- Errors should be structured enough for agents to fix calls in-session.

## CLI Surface

Magpie should have a real CLI like Alertee, but keep it smaller and knowledge-focused.

Two packaging options:

1. Keep Python `magpie` CLI for server/self-hosted operations.
2. Add a TypeScript `@magpie/cli` for hosted user workflows and MCP stdio.

Recommendation: keep Python for `serve`, `migrate`, and local import. Add TypeScript `@magpie/cli` for user-facing hosted/self-hosted use, because it matches Alertee's CLI pattern and is easier to distribute with `npx`.

Commands:

```bash
magpie login
magpie logout
magpie whoami
magpie link
magpie org list
magpie project list

magpie search "landing page brand assets" --workspace reach --project alertee
magpie read <entry-id> --resolved
magpie write --title "Alertee positioning" --file positioning.md --workspace reach --project alertee
magpie archive <entry-id>

magpie collections list --workspace reach --project alertee
magpie collections get reach.strategy alertee
magpie collections set reach.strategy alertee --file strategy.json

magpie attachments add <entry-id> ./logo.svg --role logo-primary
magpie attachments list <entry-id>

magpie import markdown ./docs --workspace erdo --project magpie
magpie mcp
```

CLI config:

- Hosted default API URL: `https://magpie.erdo.ai`.
- Override with `MAGPIE_API_URL`.
- Token from browser login, `MAGPIE_TOKEN`, or config file.
- Linked org/project stored locally, with per-command overrides.

## Web UI

Magpie's UI should become a practical operator surface, not a generic note app.

Required views:

- Knowledge browser with workspace/project filters.
- Entry editor with Markdown preview.
- Links/backlinks side panel.
- Attachments panel with upload, role, preview, copy handle, copy public URL when available.
- Collections browser with JSON document viewer/editor.
- Search page with semantic/keyword result explanation.
- Org/project/API key settings.
- Hosted onboarding: create org, create first project, connect MCP/CLI.

Avoid overbuilding a marketing document tool. The primary users are humans supervising agent memory and agents consuming it.

## Hosted Magpie

Hosted Magpie should use the same OSS server where possible.

Initial hosting target:

- Railway app service for Magpie.
- Railway Postgres with pgvector.
- Object storage for attachments.
- Custom domain `magpie.erdo.ai`.
- Email OTP/OAuth auth.
- Managed embeddings using hosted `OPENAI_API_KEY`.

The repo already has a scaffold config for Railway + Postgres + pgvector. Update it for object storage and production env:

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `SESSION_SECRET`
- `RESEND_API_KEY`
- `RESEND_FROM`
- `MAGPIE_PUBLIC_URL`
- `MAGPIE_STORAGE_PROVIDER`
- `MAGPIE_STORAGE_BUCKET`
- `MAGPIE_STORAGE_ENDPOINT`
- `MAGPIE_STORAGE_ACCESS_KEY_ID`
- `MAGPIE_STORAGE_SECRET_ACCESS_KEY`
- `MAGPIE_ASSET_PUBLIC_BASE_URL`

Hosted requirements before dogfooding:

- Backups for Postgres.
- Storage retention policy.
- Per-org quotas for entries, attachments, and embedding calls.
- Basic usage page.
- Admin-only org/user inspection.
- Import/export path so hosted users are not locked in.

## Self-Hosted Magpie

Self-hosted should be one command or one compose file.

Targets:

- Docker Compose: app + Postgres + pgvector + MinIO.
- Railway scaffold.
- Fly/Railway docs for deploying the server and managed Postgres.

Self-hosted requirements:

- Auth can be disabled for local single-user dev.
- API key auth works without email.
- Object storage can be local filesystem for dev and S3-compatible for production.
- Import/export works without hosted services.
- Embeddings are optional; keyword search works without OpenAI.

## App Adapters

Make adoption cheap by adding thin clients rather than asking every product to learn the whole REST API.

Packages:

- `@magpie/client`
- `magpie-client` Python package or module.

Adapter shape:

```ts
const memory = createMagpieMemory({
  app: "reach",
  workspace: "reach",
  project: "alertee",
  apiUrl: process.env.MAGPIE_API_URL,
  token: process.env.MAGPIE_TOKEN,
});

await memory.writeKnowledge({ title, content, type: "strategy" });
await memory.setDocument("strategy", "current", value);
await memory.search("what have we learned about enterprise buyers?");
```

Reach adoption:

- Keep jobs, drafts, publish events, analytics connections, and UI state local.
- Move project knowledge snippets, strategic memory snapshots, context-agent findings, applied learnings, and brand assets into Magpie.
- Keep a local cache/summary in the workspace only for fast UI hydration.
- Use Magpie search for prior context in background agents.

Alertee adoption:

- Keep checks, incidents, connections, alerts, and billing local.
- Move reusable diagnosis notes, runbooks, performance advisories, quiet-period rationale, incident postmortems, and check-specific context into Magpie.
- Link Magpie entries to `alertee:check:<id>`, `alertee:issue:<id>`, and `alertee:connection:<id>`.
- Store screenshots/diagrams/query snippets as attachments on diagnosis/runbook entries.

Erdo adoption:

- Keep Erdo Knowledge for Erdo product semantics while Magpie matures.
- Reuse Magpie ideas for OSS/general memory.
- Do not couple Erdo's page/event runtime to Magpie.

## Implementation Phases

### Phase 0: Product Contract

- Add this plan.
- Update README with the new positioning: "MCP-native knowledge and context store for agents and teams."
- Define the public object model in docs.
- Decide Python-only CLI vs TypeScript user CLI. Default decision: TypeScript user CLI plus Python server CLI.

### Phase 1: Tenancy And Scoping

- Normalize org/workspace/project fields.
- Add project concept if needed.
- Add role checks to all write paths.
- Add scoped API keys.
- Update REST, MCP, and UI filters.
- Add tests for visibility and cross-org isolation.

### Phase 2: Links

- Add links table.
- Parse `[[wikilinks]]` on entry create/update.
- Return links/backlinks from read/list endpoints.
- Add UI links panel.
- Add MCP `list_links` and backlink summaries in `read_knowledge`.

### Phase 3: Collections

- Add collections/documents migrations, including `value_type`.
- Add typed value validation on document writes.
- Add REST CRUD.
- Add MCP document tools.
- Add UI collection browser and JSON editor.
- Add collection/document link targets.

### Phase 4: Attachments

- Add storage abstraction: local filesystem, S3-compatible, hosted object storage.
- Add attachment table and REST upload/delete/read endpoints.
- Add attachment panel in UI.
- Add MCP and CLI attachment commands.
- Inline small SQL/text attachments in `read_knowledge`.
- Return stable `magpie:<attachment_id>` handles.
- Add public asset route for allowlisted browser-safe media.
- Add role/filename conventions to docs and agent prompts.

### Phase 5: Reference Resolution

- Add `resolve_knowledge` endpoint.
- Support `[[...]]`, `{{collection.key.path}}`, and attachment references.
- Return rendered Markdown plus dependency graph.
- Add unresolved/unauthorized diagnostics.
- Add MCP `resolve_knowledge`.

### Phase 6: CLI

- Create `cli/` TypeScript workspace.
- Implement auth/login/link/whoami.
- Implement search/read/write/import.
- Implement collection commands.
- Implement attachment commands.
- Implement `magpie mcp` stdio server for local agent setups.
- Publish as `@magpie/cli` or `@magpieai/cli`.

### Phase 7: Hosted Deployment

- Extend Railway scaffold with object storage.
- Deploy hosted Magpie to `magpie.erdo.ai`.
- Configure Postgres pgvector, storage, email, session secrets, and embeddings.
- Add backups and quotas.
- Create hosted onboarding docs.
- Dogfood with Erdo/Reach/Alertee internal orgs.

### Phase 8: App Integrations

- Add `@magpie/client`.
- Integrate Reach with opt-in env vars.
- Integrate Alertee with opt-in env vars.
- Keep local fallback paths until Magpie is stable.
- Migrate old app-specific knowledge incrementally.

## Repo Sync, Format Spec, and Viewer (Phase 9)

This is Magpie's own design. We give devs a git-native way to author knowledge locally, sync it to the server, browse it offline, and never lose it to lock-in. Our reasons, our format.

Framing: **the folder gives portability; the server gives coherence.** A folder of Markdown can't search, scope, resolve typed values, or stop drift — that's the whole reason Magpie exists. This phase adds the portability half without giving up the coherence half.

(Context only, not a driver: Google published the Open Knowledge Format on 2026-06-12 — a folder-of-Markdown spec with no runtime. Independent convergence on Markdown+frontmatter validates the model, nothing more. We are not building to their template. If OKF ever gets real adoption, our format is already shaped such that emitting it is a 1-line export — see footnote at the end.)

### Frontmatter spec

Define Magpie's own small, versioned, **closed** frontmatter schema for entry Markdown. This is a strict contract, not a free-for-all bag of keys.

- A fixed, known set of entry-describing fields only. Proposed: `magpie_version` (schema version, required), `type` (required, matches Magpie's entry-type enum), `title`, `tags`, `summary`, `source`, `status`.
- **Unknown keys are rejected on `push`** (with a clear error), not silently stored. This is deliberate: an open frontmatter bag would drift against collections and turn into a second, messy, unvalidated KV store. We already have a typed, validated KV store — that's collections.
- Hard boundary: frontmatter describes the *entry*; any structured data/values belong in a **collection**, never the frontmatter. If you're tempted to add a field, it's either a real schema change (bump `magpie_version`) or it's a collection document.
- Version the schema (`magpie_version`) so the loader can evolve it and migrate older bundles.

### Repo sync

Docs-as-code for knowledge: devs edit Markdown in their editor, review in PRs, CI pushes to the server on merge. Fits the dev-first positioning and is a workflow the Mem0/Letta/Zep crowd does not have.

- **Start one-way: `magpie push ./knowledge`.** Repo is the source of truth for curated content; the server reads the folder, upserts, generates embeddings, and becomes the search/serve index.
- Do **not** build bidirectional sync first — it needs stable IDs, timestamps, and merge handling. One-way covers ~90% of the value for a fraction of the work. Bidirectional later only if asked.

Folder layout:

```
knowledge/
├── <entry>.md                      # markdown + frontmatter (entries)
├── collections/
│   ├── _manifest.json              # canonical store/key registry (anti-drift)
│   └── <slug>.json                 # one file per store: { key: value } (repo-canonical KV only)
└── attachments/
    ├── <file>                      # binary
    └── <file>.json                 # sidecar metadata
```

### Two collection layers

Collections are **standalone**, not owned by entries (already true in code — scoped to org/workspace/project, referenced via `{{...}}` resolution). Attachments are entry-owned; collections are not. Split them by source of truth:

- **`source: repo`** (curated): config, brand tokens, definitions, positioning. Human-owned, deserves PR history. File is canonical, server mirrors it, agent writes rejected/flagged. Synced via `push`.
- **`source: server`** (live): metrics, resolved facts, agent-written runtime memory. Changes constantly, agents write it. Committing it is "committing your database" — wrong. Server is canonical, never exported to the repo (or only as a read-only snapshot). Never synced.

Same Collections primitive, a per-store source-of-truth flag, two sync policies. This resolves the live-vs-committed tension: only commit what should have a review history.

On-disk format for repo-canonical KV is **JSON**, one file per store (`collections/<slug>.json`), `{ key: value }` with types mostly inferred from JSON natives (annotate only `datetime` and `integer`-vs-`float`). Escape hatch for big/hot stores: directory form `collections/<slug>/<key>.json`; loader accepts either. No binary store at the repo layer — diffability is the whole point; the optimized store is Postgres JSONB on the server.

### Anti-drift

Drift (near-duplicate store names for the same thing, the same value under different keys) is the real risk — worse than merge conflicts, and the thing a pure folder format cannot fix. The cure is a central registry the server enforces:

- `collections/_manifest.json` (mirrored server-side): canonical stores — slug, title, optional key schema with types.
- On every write (repo `push` or agent `set_document`): unknown store → reject with nearest-match suggestion; unknown key → warn; fuzzy-match slugs to catch `reach-strategy` vs `reach_strategy`.
- Creating a store stays deliberate (Phase 3 already ships `create_collection` + missing-key hints — build duplicate detection on top).

### Export / import (our format)

Closes the open Phase 7 lock-in TODO ("import/export path so hosted users are not locked in"). This is our bundle format — the same folder layout `push` reads.

- `magpie export` → full bundle: entries (Markdown+frontmatter), repo-canonical collections (JSON), attachments (binary + sidecar), manifest.
- `magpie import <bundle>` → ingest, embed on the way in, assign scope.

### Viewer

A zero-backend static HTML view of an exported bundle:

- Great export artifact and demo: "here's your knowledge as a browsable graph, no server needed."
- Pairs with `export` — bundle + self-contained `index.html`, browsable offline.
- Makes the "you're not locked in" story tangible.

### Parked (not this phase)

- Offline search: a local SQLite mirror (`sqlite-vec` + FTS5) reproducing RRF on a laptop. Real, but a port of fusion to a second engine — separate from sync, only if people want serverless offline search. The mirror is binary; it is not the repo format.

### Footnote: OKF compatibility

Not a goal and not a driver. Because our bundle is already Markdown+frontmatter + JSON, emitting an OKF-shaped export is a near-trivial adapter we can add *only if* OKF ever gets real adoption. Until then, ignore it. Our format leads; OKF is at most a free side-export later.

## Open Questions

- Package name: `@magpie/cli`, `@magpieai/cli`, or keep only Python `magpie`?
- Hosted auth: email OTP only, GitHub OAuth, Google OAuth, or all?
- Storage provider for hosted: Railway object storage, R2, S3, or GCS?
- Should collection documents be embedded/searched directly, or only via summary fields?
- Should attachments support OCR/image captions for search in v1, or start with filename/description/parent-entry search?
- How much Erdo Knowledge should be ported versus used only as design inspiration?
- Should public asset serving be per-entry opt-in, per-project opt-in, or attachment-level opt-in?

## Success Criteria

- A new user can self-host Magpie with Postgres + object storage and connect Claude Code through MCP.
- A hosted user can create an org/project, install the CLI/MCP, and search/write/read knowledge in under five minutes.
- Reach can use Magpie for project memory without moving operational workspace state.
- Alertee can use Magpie for incident/runbook/check context without moving checks or issues.
- Agents can retrieve a brand style entry, inspect logo/image attachments, and produce deterministic landing-page assets without hotlinking or inventing logos.
- The same knowledge entry can expose Markdown, structured references, backlinks, and attachments through REST, CLI, MCP, and UI.
