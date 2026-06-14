# Magpie History Log Plan

## Positioning

Magpie needs boring, useful history: what changed, when, by whom, and enough
detail to inspect or recover trust. This is not a "context graph" or provenance
platform. It is product hygiene for a shared knowledge store.

The first version should make the existing Updates page real. Today it is derived
from current rows, so it can show recent state but not a durable sequence of
events. History v1 adds an append-only activity log, then optional revision
tables for entries and KV values.

## Goals

- Preserve a chronological record of writes across entries, KV, attachments,
  merges, archives, deletes, bulk edits, and bundle pushes.
- Keep `/api/updates` useful after deletes and repeated updates.
- Make it clear which user/token/system action changed a thing.
- Keep clients thin: REST owns write semantics; MCP, CLI, and UI inherit them.
- Add entry revision history after activity events land.
- Keep the model simple enough that agents and humans will actually use it.

## Non-Goals

- No agent reasoning traces.
- No mandatory rationale fields.
- No policy/approval workflow engine.
- No graph database.
- No full diff UI in v1.
- No attempt to reconstruct every historical state from day one.

## Current State

Magpie already has:

- `created_at`, `updated_at`, and `archived_at` on entries.
- `source`, `workspace`, `project`, `user_id`, and `org_id` on entries.
- `created_at`, `updated_at`, `created_by_user_id`, and `source` on KV stores.
- `created_at`, `updated_at`, and `created_by_user_id` on KV pairs.
- `created_at` and `created_by_user_id` on attachments.
- Archive/unarchive for entries.
- Merge behavior that archives source entries and writes string lineage into
  `source`.
- `/api/updates`, which merges recent entries and KV rows into an activity feed.
- A UI Updates page.

The gaps:

- `/api/updates` is derived from latest row state, not persisted events.
- Repeated updates collapse into one row.
- Deletes disappear from the feed.
- Entry and KV updates overwrite previous values.
- Entries do not have clean `created_by_user_id` / `updated_by_user_id` fields.
- Attachment deletes are hard deletes with no visible trace.
- Merge and bulk edit are not first-class activity records.
- The feed misses attachments, deletes, merges, bundle pushes, and actor detail.

## Phase 1: Activity Events

Add an append-only table:

```sql
CREATE TABLE activity_events (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    workspace TEXT,
    project TEXT,

    actor_user_id TEXT,
    actor_type TEXT NOT NULL DEFAULT 'unknown',
    actor_ref TEXT,

    action TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT,
    subject_title TEXT,

    metadata_json JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_activity_events_org_time
    ON activity_events (org_id, created_at DESC);

CREATE INDEX idx_activity_events_subject
    ON activity_events (subject_type, subject_id, created_at DESC);

CREATE INDEX idx_activity_events_scope_time
    ON activity_events (
        org_id,
        COALESCE(workspace, ''),
        COALESCE(project, ''),
        created_at DESC
    );
```

### Actor Fields

- `actor_user_id`: current authenticated user when available.
- `actor_type`: `user`, `token`, `system`, or `unknown`.
- `actor_ref`: optional label such as token id/prefix, MCP client, CLI, or
  bundle push source. Do not overbuild this in v1.

The current auth context only exposes user/org/role/scope. Phase 1 can record
`actor_user_id` and default `actor_type` conservatively. Token/client detail can
follow once request state exposes it cleanly.

### Actions

Start with a fixed string set:

- `entry.created`
- `entry.updated`
- `entry.archived`
- `entry.unarchived`
- `entry.deleted`
- `entry.merged`
- `entry.bulk_updated`
- `kv_store.created`
- `kv_store.deleted`
- `kv_pair.set`
- `kv_pair.deleted`
- `attachment.added`
- `attachment.deleted`
- `bundle.pushed`

Avoid generic `created` / `updated` without subject prefix. Namespaced actions
are easier to scan and safer to extend.

### Metadata

Keep metadata small and practical:

- Entry update: changed field names, not full content.
- Merge: `source_ids`, `new_entry_id`.
- Bulk edit: match, changes, matched count, updated count.
- KV set: store slug, key, value type.
- KV delete: store slug, key.
- Attachment: filename, role, media type, byte size.
- Bundle push: entry count, KV store count, workspace, project.

Do not put giant content blobs in `activity_events`.

## Phase 2: DB Helper

Add a single DB helper:

```python
async def record_activity(
    self,
    *,
    action: str,
    subject_type: str,
    subject_id: str | None = None,
    subject_title: str | None = None,
    org_id: str | None = None,
    workspace: str | None = None,
    project: str | None = None,
    actor_user_id: str | None = None,
    actor_type: str = "unknown",
    actor_ref: str | None = None,
    metadata: dict | None = None,
) -> str:
    ...
```

Rules:

- Call it inside the same transaction for multi-step writes where practical.
- For simple route-level operations, record immediately after the DB write.
- If event writing fails, the write should fail for transactional operations.
  History is part of the product contract.
- Keep all event emission server-side.

## Phase 3: Emit Events

### Entries

Emit from:

- `POST /api/entries`
- `PUT /api/entries/{id}`
- `DELETE /api/entries/{id}`
- `POST /api/entries/{id}/archive`
- `POST /api/entries/{id}/unarchive`
- `POST /api/entries/merge`
- `POST /api/entries/bulk`

For update events, load the existing entry before update and record changed
field names:

```json
{
  "changed": ["title", "content", "tags"]
}
```

Do not store full previous content in activity metadata. That belongs in
`entry_revisions`.

### KV

Emit from:

- `POST /api/kv`
- `DELETE /api/kv/{store_id}`
- `PUT /api/kv/{slug}/keys/{key}`
- `DELETE /api/kv/{slug}/keys/{key}`

KV set should record whether the key was new or existing if cheaply known.

### Attachments

Emit from:

- `POST /api/entries/{id}/attachments`
- `DELETE /api/attachments/{id}`

Use the owning entry scope for event scope.

### Bundle Push

Emit one `bundle.pushed` event after a successful push, with counts and scope.
Do not emit one event per entry in v1 unless the existing sync path can do that
without making push noisy or slow.

## Phase 4: Replace `/api/updates`

Change `/api/updates` to query `activity_events`.

Query behavior:

- Newest first.
- Filter by caller org visibility.
- Optional `workspace` and `project`.
- Limit capped to 100.
- Return old UI-compatible fields where possible:
  - `kind`
  - `action`
  - `title`
  - `entry_id`
  - `store`
  - `key`
  - `value_type`
  - `workspace`
  - `project`
  - `at`

Also return the richer event shape:

- `id`
- `subject_type`
- `subject_id`
- `subject_title`
- `actor_user_id`
- `actor_type`
- `metadata`

The UI can keep rendering a simple feed first, then add event-specific labels.

## Phase 5: Entry Revisions

After activity events land, add entry revision history.

```sql
CREATE TABLE entry_revisions (
    id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    org_id TEXT,
    workspace TEXT,
    project TEXT,

    actor_user_id TEXT,
    actor_type TEXT NOT NULL DEFAULT 'unknown',
    actor_ref TEXT,

    previous_title TEXT NOT NULL,
    previous_content TEXT NOT NULL,
    previous_tags TEXT[] NOT NULL DEFAULT '{}',
    previous_source TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_entry_revisions_entry_time
    ON entry_revisions (entry_id, created_at DESC);
```

On `PUT /api/entries/{id}`, store the previous row before overwriting when any
of `title`, `content`, `tags`, or `source` changes.

Add:

- `GET /api/entries/{id}/history`

Return newest first. Include current version separately or let the UI show the
current entry above historical revisions.

Do not build diff rendering in the backend. The first UI can show timestamp,
actor, and "view previous content".

## Phase 6: KV Revisions

Add only if needed after entry history.

```sql
CREATE TABLE kv_revisions (
    id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL REFERENCES kv_stores(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    org_id TEXT,

    actor_user_id TEXT,
    actor_type TEXT NOT NULL DEFAULT 'unknown',
    actor_ref TEXT,

    previous_value JSONB NOT NULL,
    previous_value_type TEXT NOT NULL,
    previous_summary TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_kv_revisions_key_time
    ON kv_revisions (store_id, key, created_at DESC);
```

On KV set, if a key already exists and the value/type/summary changes, store the
previous value.

Potential endpoint:

- `GET /api/kv/{slug}/keys/{key}/history`

## Phase 7: UI

### Updates Page

Keep it compact:

- Icon per subject type.
- Action label.
- Subject title.
- Scope badge.
- Relative timestamp.
- Optional actor display when available.

Use event metadata only for small labels:

- `merged 3 entries`
- `bulk updated 14 entries`
- `set config/trial_days`
- `added logo-primary`

### Entry Page

After `entry_revisions` lands:

- Add a `History` section/tab.
- Show previous versions newest first.
- Click to inspect previous Markdown.
- Do not add restore in v1 unless implementation is trivial.

## Phase 8: REST / MCP / CLI / Docs Parity

Public capability changes need parity.

REST:

- `GET /api/updates`
- `GET /api/entries/{id}/history` after entry revisions.
- Optional `GET /api/kv/{slug}/keys/{key}/history` after KV revisions.

MCP:

- Add `list_updates` if agents need to inspect recent store changes.
- Add `entry_history` after entry revisions if useful.

TypeScript CLI:

- Add `magpie updates`.
- Add `magpie history <entry-id>` after entry revisions.

Python CLI:

- Only add commands if needed for server ops. Keep the user-facing CLI in TS.

Docs:

- Update `docs/site/reference/api.mdx`.
- Add or extend a concept page for history/activity.
- Update MCP tools docs if MCP tools are added.
- Update CLI docs if commands are added.

## Testing

Add focused tests:

- Migration creates indexes and table shape.
- Entry create/update/archive/unarchive/delete emits events.
- Merge emits one merge event with source ids.
- Bulk edit emits one bulk event.
- KV create/set/delete emits events.
- Attachment add/delete emits events.
- `/api/updates` reads from `activity_events`.
- Visibility filters hide other orgs' events.
- Workspace/project filters work.
- Entry update creates a revision only when meaningful fields change.

Avoid snapshot-heavy tests for UI copy.

## Rollout Order

1. Add `activity_events` migration.
2. Add `db.record_activity`.
3. Emit entry events.
4. Emit KV events.
5. Emit attachment events.
6. Emit merge/bulk/bundle events.
7. Move `/api/updates` to events.
8. Update UI Updates page only as needed.
9. Update REST docs.
10. Add MCP/CLI read tools if they feel useful after REST/UI land.
11. Add `entry_revisions`.
12. Add entry history endpoint and UI.
13. Consider KV revisions.

## Product Bar

This work is done when a user can answer:

- What changed recently?
- Who or what changed it?
- When did it happen?
- What object did it touch?
- Did this entry change multiple times?
- What was the previous version of this entry?

It is not done only because the Updates page has rows. The log has to survive
overwrites and deletes.
