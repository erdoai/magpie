-- Phase 1: tenancy and scoping
-- workspace = broad product/app namespace (e.g. "reach"), project = narrower
-- work area within it (e.g. "alertee"). Both are free-form slugs, paired.

-- entries.project_id was an opaque, unused scoping field — normalize to `project`
ALTER TABLE entries RENAME COLUMN project_id TO project;
ALTER INDEX idx_entries_project RENAME TO idx_entries_project_old;
CREATE INDEX IF NOT EXISTS idx_entries_scope ON entries(org_id, workspace, project);
DROP INDEX IF EXISTS idx_entries_project_old;

-- API keys can be scoped to a workspace/project and carry a role
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS workspace TEXT;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS project TEXT;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'editor';

-- Org roles: owner, admin, editor, viewer (legacy 'member' becomes editor)
UPDATE org_members SET role = 'editor' WHERE role = 'member';
ALTER TABLE org_members ALTER COLUMN role SET DEFAULT 'editor';
