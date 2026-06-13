-- Two collection layers: source of truth.
--
--   'server' (default) — live, agent-written runtime KV (metrics, resolved
--                        facts). Server is canonical; never exported to a repo.
--   'repo'             — curated KV (config, brand tokens, definitions). The
--                        bundle file is canonical; agent writes are rejected,
--                        and the store is (re)synced by `magpie push`.
--
-- This keeps live data out of git (no "committing your database" churn) while
-- letting curated data live in version control.

ALTER TABLE collections ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'server';
