-- Add workspace column for team-level knowledge sharing
ALTER TABLE entries ADD COLUMN IF NOT EXISTS workspace TEXT;
CREATE INDEX IF NOT EXISTS idx_entries_workspace ON entries(workspace);

-- Add org_id index (column exists from 001 but wasn't indexed)
CREATE INDEX IF NOT EXISTS idx_entries_org_workspace ON entries(org_id, workspace);
