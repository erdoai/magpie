-- Entry revision history: the previous content of an entry, captured the moment
-- before an update overwrites it. The activity log (018) records THAT a change
-- happened; this records WHAT the entry looked like before, so a meaningful edit
-- can be inspected or recovered. One row per overwriting update — only when a
-- material field (title/content/tags/source) actually changes, so reorder/scope
-- churn doesn't pile up noise. Cascade-deletes with the entry.
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
