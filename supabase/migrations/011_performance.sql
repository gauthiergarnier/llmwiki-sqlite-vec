-- RLS: evaluate auth.uid() once per statement instead of once per row.

ALTER POLICY users_select ON users USING (id = (select auth.uid()));
ALTER POLICY api_keys_select ON api_keys USING (user_id = (select auth.uid()));
ALTER POLICY knowledge_bases_select ON knowledge_bases USING (user_id = (select auth.uid()));
ALTER POLICY documents_select ON documents USING (user_id = (select auth.uid()));
ALTER POLICY document_chunks_select ON document_chunks USING (user_id = (select auth.uid()));
ALTER POLICY knowledge_base_events_select ON knowledge_base_events USING (user_id = (select auth.uid()));
ALTER POLICY document_pages_select ON document_pages USING (
    EXISTS (
        SELECT 1 FROM documents
        WHERE documents.id = document_pages.document_id
          AND documents.user_id = (select auth.uid())
    )
);

-- Users never update their own row directly (quota columns live there); the API writes as owner.
DROP POLICY IF EXISTS users_update ON users;

-- document_references_write is FOR ALL, so it already grants SELECT.
DROP POLICY document_references_select ON document_references;
ALTER POLICY document_references_write ON document_references
    USING (knowledge_base_id IN (SELECT id FROM knowledge_bases WHERE user_id = (select auth.uid())))
    WITH CHECK (knowledge_base_id IN (SELECT id FROM knowledge_bases WHERE user_id = (select auth.uid())));

-- Activity events only depend on these columns; skip the trigger (and its full-content compare) for highlight/status/version writes.

DROP TRIGGER document_activity_update ON documents;
CREATE TRIGGER document_activity_update
    AFTER UPDATE OF content, filename, title, path, tags, date, metadata, archived ON documents
    FOR EACH ROW EXECUTE FUNCTION record_document_updated();

-- Indexes the queries can actually use.

CREATE INDEX idx_documents_user_source_url
    ON documents (user_id, (metadata->>'source_url'))
    WHERE (metadata->>'source_url') IS NOT NULL AND NOT archived;

CREATE INDEX idx_documents_user_parent_document
    ON documents (user_id, (metadata->>'parent_document_id'))
    WHERE (metadata->>'parent_document_id') IS NOT NULL;

-- Unused indexes, maintained on every write.

DROP INDEX idx_documents_source_url;
DROP INDEX idx_documents_content_pgroonga;
DROP INDEX idx_documents_tags;
DROP INDEX idx_documents_date;
DROP INDEX idx_knowledge_bases_public_lookup;
