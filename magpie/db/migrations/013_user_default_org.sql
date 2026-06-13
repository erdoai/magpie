-- A user's chosen "active" org, used when no X-Organization-ID header is sent
-- (e.g. cookie-session web requests). NULL = fall back to first membership.
-- ON DELETE SET NULL so deleting an org clears stale defaults automatically.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS default_org_id TEXT REFERENCES orgs(id) ON DELETE SET NULL;
