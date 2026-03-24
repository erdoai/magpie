-- pgvector support (requires pgvector extension installed on the server)
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE entries ADD COLUMN IF NOT EXISTS embedding vector(1536);

CREATE INDEX IF NOT EXISTS idx_entries_embedding ON entries
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
