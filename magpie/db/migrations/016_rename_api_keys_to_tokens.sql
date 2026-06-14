-- Rename the per-user credential "API key" to "token" to avoid confusion with
-- KV store keys. Pure rename; data and the UNIQUE(token_hash) constraint are
-- preserved. The static-auth env var API_KEY is unrelated and unchanged.
ALTER TABLE api_keys RENAME TO tokens;
ALTER TABLE tokens RENAME COLUMN key_hash TO token_hash;
ALTER TABLE tokens RENAME COLUMN key_prefix TO token_prefix;
