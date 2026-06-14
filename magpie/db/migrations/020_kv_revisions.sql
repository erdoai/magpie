-- KV value revision history: the previous value of a KV pair, captured before a
-- set overwrites it. Mirrors entry_revisions (019) for typed KV stores — records
-- WHAT a key held before, when the value/type/summary actually changes. Keyed by
-- (store_id, key) since a pair is identified by both. Cascade-deletes with the
-- store.
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
