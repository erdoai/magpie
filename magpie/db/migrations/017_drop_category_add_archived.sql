-- Drop the PARA category taxonomy (project/area/resource/archive). It carried
-- little weight in practice. "Archive" was the one meaningful state, so it
-- becomes an explicit lifecycle column: archived_at (NULL = active). Existing
-- archived rows carry their state over; everything else becomes active.
ALTER TABLE entries ADD COLUMN archived_at TIMESTAMPTZ;
UPDATE entries SET archived_at = updated_at WHERE category = 'archive';
ALTER TABLE entries DROP COLUMN category;
CREATE INDEX idx_entries_archived_at ON entries(archived_at);
