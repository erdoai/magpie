-- Path-as-identity for bundle sync (`magpie push`).
--
-- An entry synced from a knowledge bundle is identified by its relative path
-- within that bundle, scoped to (org, workspace, project). Re-pushing the same
-- path updates the same entry instead of creating a duplicate. NULL source_path
-- means the entry was not created from a bundle (API/UI/MCP/import).

ALTER TABLE entries ADD COLUMN IF NOT EXISTS source_path TEXT;

-- One entry per (scope, path). COALESCE so NULL scope fields still collide
-- deterministically; partial index leaves non-bundle entries unconstrained.
CREATE UNIQUE INDEX IF NOT EXISTS idx_entries_source_path
    ON entries (
        COALESCE(org_id, ''),
        COALESCE(workspace, ''),
        COALESCE(project, ''),
        source_path
    )
    WHERE source_path IS NOT NULL;
