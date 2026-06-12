-- Phase 3: named JSON document collections — structured context read whole
-- by key, not row analytics. org_id NULL = global (matches entries).
CREATE TABLE collections (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    workspace TEXT,
    project TEXT,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    visibility TEXT NOT NULL DEFAULT 'org',
    created_by_user_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- UNIQUE constraint would treat NULL scopes as distinct; coalesce instead
CREATE UNIQUE INDEX idx_collections_scope_slug ON collections (
    COALESCE(org_id, ''), COALESCE(workspace, ''), COALESCE(project, ''), slug
);

CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    org_id TEXT,
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

CREATE INDEX idx_documents_collection ON documents(collection_id);
