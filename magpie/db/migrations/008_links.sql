-- Phase 2: durable link edges parsed from [[wikilinks]] in entry Markdown.
-- Polymorphic source/target so collections/documents can link too (Phase 3).
-- org_id mirrors the source entry's org (NULL = global), used for visibility.
CREATE TABLE links (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    source_type TEXT NOT NULL DEFAULT 'entry',
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL, -- entry, url, resource, unresolved
    target_id TEXT,            -- set when target_type = 'entry'
    target_ref TEXT,           -- URL or product resource ref (e.g. alertee:check:42)
    link_text TEXT NOT NULL,   -- display text as written
    normalized_target TEXT NOT NULL, -- lowercased target for matching/re-resolution
    metadata_json JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_links_source ON links(source_type, source_id);
CREATE INDEX idx_links_target ON links(target_type, target_id);
CREATE INDEX idx_links_normalized ON links(normalized_target);
