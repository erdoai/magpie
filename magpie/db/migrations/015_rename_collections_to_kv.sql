-- Reclaim the word "collections" for a future knowledge-grouping concept.
-- The typed key->value store it used to name is now "kv": a `kv_store` holds
-- `kv_pairs` (key -> typed value). Pure rename; data is preserved. Foreign keys
-- and the (store_id, key) uniqueness follow the table/column automatically.
ALTER TABLE collections RENAME TO kv_stores;
ALTER TABLE documents RENAME TO kv_pairs;
ALTER TABLE kv_pairs RENAME COLUMN collection_id TO store_id;
ALTER INDEX idx_collections_scope_slug RENAME TO idx_kv_stores_scope_slug;
ALTER INDEX idx_documents_collection RENAME TO idx_kv_pairs_store;
