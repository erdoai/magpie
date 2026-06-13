-- Projects within workspaces.
-- Mirrors `workspaces` (a managed registry under an org); a project is a
-- managed child of a workspace, completing the org -> workspace -> project
-- hierarchy. Entry/collection tagging stays slug-string based (entries.project),
-- exactly like entries.workspace — this table is the navigable registry, not a
-- hard FK constraint on tagged rows.
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, slug)
);

CREATE INDEX idx_projects_workspace ON projects(workspace_id);
