-- Phase 4: attachments owned by knowledge entries — logos, screenshots,
-- SQL snippets, briefs, PDFs. Not random bucket files: every attachment
-- belongs to an entry and dies with it.
CREATE TABLE attachments (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    kind TEXT NOT NULL, -- image, sql, text, pdf, file
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    byte_size BIGINT NOT NULL,
    description TEXT,
    role TEXT, -- logo-primary, favicon-32x32, hero-*, product-*, screenshot-*, query-*, source
    public BOOLEAN NOT NULL DEFAULT FALSE, -- serve via /public/assets/:id (browser-safe media only)
    metadata_json JSONB NOT NULL DEFAULT '{}',
    created_by_user_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_attachments_entry ON attachments(entry_id);
CREATE INDEX idx_attachments_role ON attachments(role);
