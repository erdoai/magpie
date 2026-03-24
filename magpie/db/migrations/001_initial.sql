-- Knowledge entries (PARA: Projects / Areas / Resources / Archives)
CREATE TABLE entries (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'resource',
    tags TEXT[] DEFAULT '{}',
    source TEXT,
    -- Scoping
    user_id TEXT,
    project_id TEXT,
    org_id TEXT,
    -- Search (tsvector — always available)
    search_vector tsvector,
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_entries_category ON entries(category);
CREATE INDEX idx_entries_user ON entries(user_id);
CREATE INDEX idx_entries_project ON entries(project_id);
CREATE INDEX idx_entries_org ON entries(org_id);
CREATE INDEX idx_entries_tags ON entries USING gin(tags);
CREATE INDEX idx_entries_search ON entries USING gin(search_vector);
CREATE INDEX idx_entries_updated ON entries(updated_at DESC);

-- Auto-update tsvector on insert/update
CREATE OR REPLACE FUNCTION entries_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.content, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(NEW.tags, ' '), '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER entries_search_vector_trigger
    BEFORE INSERT OR UPDATE ON entries
    FOR EACH ROW EXECUTE FUNCTION entries_search_vector_update();
