-- Surface highlight + comment content through MCP search.
-- See docs/highlights-in-search-spec.md.

-- New columns on document_chunks:
--   source_content   — immutable raw chunk text (what the chunker produced)
--   annotations_text — materialized footnote-body block of highlights/comments
--                      touching this chunk; rebuilt on highlight CRUD
--   has_highlight    — partial-index target for the "annotated only" filter
-- `content` (existing) becomes source_content + annotations_text, written
-- atomically by the highlight CRUD service methods. The existing pgroonga
-- index on `content` keeps working — content stays the searchable column.
ALTER TABLE document_chunks
  ADD COLUMN source_content   text NOT NULL DEFAULT '',
  ADD COLUMN annotations_text text,
  ADD COLUMN has_highlight    boolean NOT NULL DEFAULT false;

-- Backfill source_content from existing content.
UPDATE document_chunks SET source_content = content WHERE source_content = '';

-- Drop the chunk-length CHECK on `content`. Annotations make content
-- mutable and potentially larger than the original 10k cap. The chunker
-- still enforces 10k on source_content in code
-- (api/services/chunker.py MAX_CHUNK_CHARS).
ALTER TABLE document_chunks DROP CONSTRAINT IF EXISTS document_chunks_content_check;

-- Partial index for "search but only annotated chunks". Small and fast
-- because it indexes only the small subset of rows where has_highlight = true.
CREATE INDEX idx_chunks_annotated
  ON document_chunks (knowledge_base_id) WHERE has_highlight = true;

-- No highlight backfill: this feature ships before any user has created
-- a highlight or comment, so there is nothing to materialize. All future
-- highlight CRUD writes through the Python materializer in
-- api/services/highlight_chunks.py inside the highlight service methods.
