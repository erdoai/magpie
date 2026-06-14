-- Append-only activity log: a durable sequence of write events across the
-- store. Until now /api/updates was derived from current row state, so it
-- could show recent state but not history — repeated updates collapsed into
-- one row and deletes vanished. This table records what changed, when, and by
-- whom, surviving overwrites and deletes. Revision tables (entry/kv) come
-- later; this is the event spine they hang off.
CREATE TABLE activity_events (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    workspace TEXT,
    project TEXT,

    -- Who acted. actor_user_id is the authenticated user when known;
    -- actor_type is user | token | system | unknown; actor_ref is an optional
    -- label (token id, client) — kept deliberately thin in v1.
    actor_user_id TEXT,
    actor_type TEXT NOT NULL DEFAULT 'unknown',
    actor_ref TEXT,

    -- What happened. Namespaced action (e.g. "entry.created"), the subject's
    -- type/id, and a denormalized title so the feed renders without a join
    -- back to a row that may since have been deleted.
    action TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT,
    subject_title TEXT,

    -- Small, practical detail only (changed field names, counts, kv key) —
    -- never full content blobs. Revisions hold previous content.
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
