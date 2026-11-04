-- Private, append-only activity feed per knowledge base.
-- Triggers capture document mutations in the same transaction as the write;
-- events snapshot titles and paths so history survives document deletion.

CREATE TABLE knowledge_base_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'tracking.started', 'wiki.created',
        'page.created', 'page.updated', 'page.archived', 'page.restored', 'page.deleted',
        'source.added', 'source.updated', 'source.deleted'
    )),
    subject_kind TEXT NOT NULL CHECK (subject_kind IN ('wiki', 'wiki_page', 'source')),
    document_id UUID,
    document_number INTEGER,
    document_version INTEGER,
    subject_title TEXT NOT NULL,
    subject_path TEXT,
    event_key TEXT UNIQUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_kb_events_feed ON knowledge_base_events (knowledge_base_id, id DESC);
CREATE INDEX idx_kb_events_user ON knowledge_base_events (user_id, id DESC);

-- Owner-only reads; all writes go through the security-definer functions below.
ALTER TABLE knowledge_base_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY knowledge_base_events_select ON knowledge_base_events
    FOR SELECT USING (user_id = auth.uid());

REVOKE ALL ON knowledge_base_events FROM anon;
REVOKE INSERT, UPDATE, DELETE ON knowledge_base_events FROM authenticated;
GRANT SELECT ON knowledge_base_events TO authenticated;

-- index.json and log.md are structural files; hidden/asset rows are web-clip internals.
CREATE FUNCTION kb_event_subject_is_visible(doc documents)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT COALESCE(doc.metadata->'hidden', 'false'::jsonb) <> 'true'::jsonb
       AND COALESCE(doc.metadata->'asset', 'false'::jsonb) <> 'true'::jsonb
       AND NOT (doc.path = '/wiki/' AND doc.filename IN ('index.json', 'log.md'));
$$;

CREATE FUNCTION kb_event_subject_kind(doc documents)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE WHEN doc.path LIKE '/wiki/%' THEN 'wiki_page' ELSE 'source' END;
$$;

-- A source flipping pending/processing -> ready with its first extracted content
-- is the completion of the original upload, not a user edit.
CREATE FUNCTION kb_event_is_initial_extraction(old_row documents, new_row documents)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT old_row.path NOT LIKE '/wiki/%'
       AND old_row.content IS NULL
       AND old_row.status IN ('pending', 'processing')
       AND new_row.status = 'ready';
$$;

CREATE FUNCTION kb_event_changed_fields(old_row documents, new_row documents)
RETURNS JSONB
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    changes JSONB := '[]'::jsonb;
BEGIN
    IF old_row.content IS DISTINCT FROM new_row.content
        AND NOT kb_event_is_initial_extraction(old_row, new_row) THEN
        changes := changes || '["content"]'::jsonb;
    END IF;
    IF old_row.filename IS DISTINCT FROM new_row.filename
        OR old_row.title IS DISTINCT FROM new_row.title THEN
        changes := changes || '["title"]'::jsonb;
    END IF;
    IF old_row.path IS DISTINCT FROM new_row.path THEN
        changes := changes || '["path"]'::jsonb;
    END IF;
    IF old_row.tags IS DISTINCT FROM new_row.tags THEN
        changes := changes || '["tags"]'::jsonb;
    END IF;
    IF old_row.date IS DISTINCT FROM new_row.date THEN
        changes := changes || '["date"]'::jsonb;
    END IF;
    IF (old_row.metadata->'properties') IS DISTINCT FROM (new_row.metadata->'properties') THEN
        changes := changes || '["properties"]'::jsonb;
    END IF;
    RETURN changes;
END;
$$;

CREATE FUNCTION insert_kb_event(
    doc documents,
    evt_type TEXT,
    evt_changes JSONB,
    evt_key TEXT,
    evt_occurred_at TIMESTAMPTZ
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO knowledge_base_events (
        knowledge_base_id, user_id, event_type, subject_kind,
        document_id, document_number, document_version,
        subject_title, subject_path, event_key, metadata, occurred_at
    ) VALUES (
        doc.knowledge_base_id,
        doc.user_id,
        evt_type,
        kb_event_subject_kind(doc),
        doc.id,
        doc.document_number,
        doc.version,
        COALESCE(NULLIF(doc.title, ''), doc.filename),
        doc.path || doc.filename,
        evt_key,
        jsonb_build_object('file_type', doc.file_type, 'file_size', doc.file_size)
            || CASE WHEN evt_changes IS NULL THEN '{}'::jsonb
               ELSE jsonb_build_object('changes', evt_changes) END,
        evt_occurred_at
    )
    ON CONFLICT (event_key) DO NOTHING;
END;
$$;

REVOKE EXECUTE ON FUNCTION insert_kb_event(documents, TEXT, JSONB, TEXT, TIMESTAMPTZ)
    FROM PUBLIC, anon, authenticated;

CREATE FUNCTION record_wiki_created()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO knowledge_base_events (
        knowledge_base_id, user_id, event_type, subject_kind,
        subject_title, event_key, occurred_at
    ) VALUES (
        NEW.id, NEW.user_id, 'wiki.created', 'wiki',
        NEW.name, 'kb:' || NEW.id::text || ':created', NEW.created_at
    )
    ON CONFLICT (event_key) DO NOTHING;
    RETURN NEW;
END;
$$;

-- Scaffolded overview.md is part of wiki.created, not a separate user action.
CREATE FUNCTION record_document_created()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NOT kb_event_subject_is_visible(NEW)
        OR (NEW.path = '/wiki/' AND NEW.filename = 'overview.md') THEN
        RETURN NEW;
    END IF;
    PERFORM insert_kb_event(
        NEW,
        CASE kb_event_subject_kind(NEW) WHEN 'wiki_page' THEN 'page.created' ELSE 'source.added' END,
        NULL,
        'doc:' || NEW.id::text || ':created',
        NEW.created_at
    );
    RETURN NEW;
END;
$$;

CREATE FUNCTION record_document_updated()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    kind TEXT := kb_event_subject_kind(NEW);
    changes JSONB;
BEGIN
    IF NOT kb_event_subject_is_visible(NEW) THEN
        RETURN NEW;
    END IF;

    IF NOT OLD.archived AND NEW.archived THEN
        PERFORM insert_kb_event(
            NEW,
            CASE WHEN kind = 'wiki_page' THEN 'page.archived' ELSE 'source.deleted' END,
            NULL, NULL, now()
        );
    ELSIF OLD.archived AND NOT NEW.archived THEN
        PERFORM insert_kb_event(
            NEW,
            CASE WHEN kind = 'wiki_page' THEN 'page.restored' ELSE 'source.added' END,
            NULL, NULL, now()
        );
    ELSE
        changes := kb_event_changed_fields(OLD, NEW);
        IF jsonb_array_length(changes) > 0 THEN
            PERFORM insert_kb_event(
                NEW,
                CASE WHEN kind = 'wiki_page' THEN 'page.updated' ELSE 'source.updated' END,
                changes, NULL, now()
            );
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- A whole-wiki delete cascades documents and events together; skip child rows
-- once the parent is gone so the cascade doesn't resurrect per-document events.
CREATE FUNCTION record_document_deleted()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM knowledge_bases WHERE id = OLD.knowledge_base_id)
        OR NOT kb_event_subject_is_visible(OLD) THEN
        RETURN OLD;
    END IF;
    PERFORM insert_kb_event(
        OLD,
        CASE kb_event_subject_kind(OLD) WHEN 'wiki_page' THEN 'page.deleted' ELSE 'source.deleted' END,
        NULL, NULL, now()
    );
    RETURN OLD;
END;
$$;

CREATE TRIGGER knowledge_base_activity_insert
    AFTER INSERT ON knowledge_bases
    FOR EACH ROW EXECUTE FUNCTION record_wiki_created();

CREATE TRIGGER document_activity_insert
    AFTER INSERT ON documents
    FOR EACH ROW EXECUTE FUNCTION record_document_created();

CREATE TRIGGER document_activity_update
    AFTER UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION record_document_updated();

CREATE TRIGGER document_activity_delete
    AFTER DELETE ON documents
    FOR EACH ROW EXECUTE FUNCTION record_document_deleted();

-- Backfill only facts the current schema knows exactly. updated_at also moves
-- on processing and highlight writes, so no historical edit events are invented.
INSERT INTO knowledge_base_events (
    knowledge_base_id, user_id, event_type, subject_kind,
    subject_title, event_key, occurred_at
)
SELECT id, user_id, 'wiki.created', 'wiki', name,
       'kb:' || id::text || ':created', created_at
FROM knowledge_bases
ON CONFLICT (event_key) DO NOTHING;

INSERT INTO knowledge_base_events (
    knowledge_base_id, user_id, event_type, subject_kind,
    document_id, document_number, document_version,
    subject_title, subject_path, event_key, metadata, occurred_at
)
SELECT
    d.knowledge_base_id,
    d.user_id,
    CASE WHEN d.path LIKE '/wiki/%' THEN 'page.created' ELSE 'source.added' END,
    CASE WHEN d.path LIKE '/wiki/%' THEN 'wiki_page' ELSE 'source' END,
    d.id,
    d.document_number,
    d.version,
    COALESCE(NULLIF(d.title, ''), d.filename),
    d.path || d.filename,
    'doc:' || d.id::text || ':created',
    jsonb_build_object('file_type', d.file_type, 'file_size', d.file_size),
    d.created_at
FROM documents d
WHERE NOT d.archived
  AND COALESCE(d.metadata->'hidden', 'false'::jsonb) <> 'true'::jsonb
  AND COALESCE(d.metadata->'asset', 'false'::jsonb) <> 'true'::jsonb
  AND NOT (d.path = '/wiki/' AND d.filename IN ('index.json', 'log.md', 'overview.md'))
ORDER BY d.created_at, d.id
ON CONFLICT (event_key) DO NOTHING;

INSERT INTO knowledge_base_events (
    knowledge_base_id, user_id, event_type, subject_kind,
    subject_title, event_key, occurred_at
)
SELECT id, user_id, 'tracking.started', 'wiki', name,
       'kb:' || id::text || ':tracking-started', now()
FROM knowledge_bases
ON CONFLICT (event_key) DO NOTHING;
