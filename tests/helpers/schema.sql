-- Test schema: mock Supabase auth functions + main migration (no PGroonga)

DROP SCHEMA IF EXISTS auth CASCADE;
CREATE SCHEMA auth;

CREATE TABLE auth.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT,
    raw_user_meta_data JSONB DEFAULT '{}'
);

CREATE OR REPLACE FUNCTION auth.uid() RETURNS UUID
LANGUAGE sql STABLE
AS $$
    SELECT COALESCE(
        nullif(current_setting('request.jwt.claims', true), '')::json->>'sub',
        NULL
    )::uuid
$$;

CREATE OR REPLACE FUNCTION auth.jwt() RETURNS JSON
LANGUAGE sql STABLE
AS $$
    SELECT COALESCE(
        nullif(current_setting('request.jwt.claims', true), ''),
        '{}'
    )::json
$$;

DO $$ BEGIN
    CREATE ROLE authenticated NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TYPE document_status AS ENUM ('pending', 'processing', 'ready', 'failed', 'archived');

CREATE TABLE users (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    onboarded BOOLEAN NOT NULL DEFAULT false,
    page_limit INTEGER NOT NULL DEFAULT 500,
    storage_limit_bytes BIGINT NOT NULL DEFAULT 1073741824,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

CREATE TABLE api_keys (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE knowledge_bases (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    kind TEXT NOT NULL DEFAULT 'wiki' CHECK (kind IN ('wiki', 'course')),
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    UNIQUE(user_id, slug),
    UNIQUE(user_id, name)
);

CREATE TABLE documents (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    filename TEXT NOT NULL,
    title TEXT,
    path TEXT DEFAULT '/' NOT NULL,
    file_type TEXT NOT NULL,
    file_size BIGINT DEFAULT 0 NOT NULL,
    document_number INTEGER,
    status document_status DEFAULT 'pending' NOT NULL,
    page_count INTEGER CHECK (page_count IS NULL OR page_count <= 300),
    content TEXT,
    tags TEXT[] DEFAULT '{}' NOT NULL,
    url TEXT,
    date TEXT,
    metadata JSONB,
    error_message TEXT,
    version INTEGER DEFAULT 0 NOT NULL,
    sort_order INTEGER DEFAULT 0,
    parser TEXT,
    archived BOOLEAN DEFAULT false NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

CREATE TABLE document_pages (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    content TEXT NOT NULL CHECK (length(content) <= 500000),
    elements JSONB,
    UNIQUE(document_id, page)
);

CREATE TABLE document_chunks (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    -- `content` is the materialized form (source + annotations) used by FTS.
    content TEXT NOT NULL,
    source_content TEXT NOT NULL DEFAULT '' CHECK (length(source_content) <= 10000),
    annotations_text TEXT,
    has_highlight BOOLEAN NOT NULL DEFAULT false,
    page INTEGER,
    start_char INTEGER,
    token_count INTEGER NOT NULL,
    header_breadcrumb TEXT,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    UNIQUE(document_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunks_annotated
    ON document_chunks(knowledge_base_id) WHERE has_highlight = true;

CREATE TABLE quiz_grade_attempts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

CREATE INDEX idx_quiz_grade_attempts_user_created
    ON quiz_grade_attempts (user_id, created_at);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS stale_since TIMESTAMPTZ;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS highlights JSONB NOT NULL DEFAULT '[]'::jsonb;
CREATE INDEX IF NOT EXISTS idx_documents_source_url
    ON documents (user_id, (metadata->>'source_url'))
    WHERE metadata ? 'source_url' AND NOT archived;

CREATE TABLE document_references (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    source_document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    target_document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    reference_type TEXT NOT NULL CHECK (reference_type IN ('cites', 'links_to')),
    page INTEGER,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    UNIQUE(source_document_id, target_document_id, reference_type)
);

CREATE INDEX idx_refs_source ON document_references(source_document_id);
CREATE INDEX idx_refs_target ON document_references(target_document_id);

CREATE POLICY document_references_select ON document_references
    FOR SELECT TO authenticated
    USING (knowledge_base_id IN (
        SELECT id FROM knowledge_bases WHERE user_id = auth.uid()
    ));

CREATE POLICY document_references_write ON document_references
    FOR ALL TO authenticated
    USING (knowledge_base_id IN (
        SELECT id FROM knowledge_bases WHERE user_id = auth.uid()
    ))
    WITH CHECK (knowledge_base_id IN (
        SELECT id FROM knowledge_bases WHERE user_id = auth.uid()
    ));

ALTER TABLE document_references ENABLE ROW LEVEL SECURITY;

CREATE INDEX idx_documents_knowledge_base_id ON documents(knowledge_base_id);
CREATE INDEX idx_documents_user_id ON documents(user_id);
CREATE INDEX idx_documents_tags ON documents USING GIN(tags);
CREATE INDEX idx_documents_kb_path ON documents(knowledge_base_id, path);
CREATE INDEX idx_documents_kb_status ON documents(knowledge_base_id, status) WHERE NOT archived;
CREATE INDEX idx_documents_date ON documents(date) WHERE date IS NOT NULL;
CREATE INDEX idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX idx_chunks_kb ON document_chunks(knowledge_base_id);
CREATE INDEX idx_chunks_doc ON document_chunks(document_id);

-- PGroonga indexes intentionally omitted (requires C extension)

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_bases ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE quiz_grade_attempts ENABLE ROW LEVEL SECURITY;

CREATE POLICY users_select ON users
    FOR SELECT USING (id = auth.uid());

CREATE POLICY users_update ON users
    FOR UPDATE USING (id = auth.uid());

CREATE POLICY api_keys_select ON api_keys
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY knowledge_bases_select ON knowledge_bases
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY documents_select ON documents
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY document_pages_select ON document_pages
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM documents
            WHERE documents.id = document_pages.document_id
              AND documents.user_id = auth.uid()
        )
    );

CREATE POLICY document_chunks_select ON document_chunks
    FOR SELECT USING (user_id = auth.uid());

CREATE OR REPLACE FUNCTION generate_slug(name TEXT, p_user_id UUID)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    base_slug TEXT;
    candidate TEXT;
    counter INTEGER := 0;
BEGIN
    base_slug := lower(regexp_replace(trim(name), '[^a-zA-Z0-9]+', '-', 'g'));
    base_slug := trim(both '-' from base_slug);
    IF base_slug = '' THEN
        base_slug := 'untitled';
    END IF;
    candidate := base_slug;
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM knowledge_bases
            WHERE slug = candidate AND user_id = p_user_id
        ) THEN
            RETURN candidate;
        END IF;
        counter := counter + 1;
        candidate := base_slug || '-' || counter;
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.users (id, email, display_name)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data ->> 'display_name', NEW.raw_user_meta_data ->> 'full_name')
    );
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION set_knowledge_base_slug()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.slug IS NULL OR NEW.slug = '' THEN
        NEW.slug := generate_slug(NEW.name, NEW.user_id);
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION handle_new_user();

CREATE TRIGGER set_knowledge_base_slug
    BEFORE INSERT ON knowledge_bases
    FOR EACH ROW
    EXECUTE FUNCTION set_knowledge_base_slug();

CREATE TRIGGER set_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER set_knowledge_bases_updated_at
    BEFORE UPDATE ON knowledge_bases
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER set_documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION set_document_number()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext(NEW.knowledge_base_id::text));
    NEW.document_number := COALESCE(
        (SELECT MAX(document_number) FROM documents WHERE knowledge_base_id = NEW.knowledge_base_id),
        0
    ) + 1;
    RETURN NEW;
END;
$$;

CREATE TRIGGER set_document_number
    BEFORE INSERT ON documents
    FOR EACH ROW
    EXECUTE FUNCTION set_document_number();

CREATE UNIQUE INDEX idx_documents_kb_number ON documents(knowledge_base_id, document_number);

GRANT USAGE ON SCHEMA public TO authenticated;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO authenticated;
-- Supabase grants full CRUD to authenticated by default; mirror those grants
-- so RLS write tests and scoped_execute work correctly.
GRANT INSERT, UPDATE, DELETE ON document_references TO authenticated;
GRANT INSERT, UPDATE, DELETE ON documents TO authenticated;
GRANT INSERT, UPDATE, DELETE ON knowledge_bases TO authenticated;
GRANT UPDATE ON users TO authenticated;

-- Document change notification trigger (mirrors 003_document_notify.sql)
CREATE OR REPLACE FUNCTION notify_document_change() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    PERFORM pg_notify('document_changes', json_build_object(
      'event', TG_OP,
      'id', OLD.id::text,
      'knowledge_base_id', OLD.knowledge_base_id::text,
      'user_id', OLD.user_id::text
    )::text);
    RETURN OLD;
  ELSE
    PERFORM pg_notify('document_changes', json_build_object(
      'event', TG_OP,
      'id', NEW.id::text,
      'knowledge_base_id', NEW.knowledge_base_id::text,
      'user_id', NEW.user_id::text
    )::text);
    RETURN NEW;
  END IF;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER document_change_trigger
  AFTER INSERT OR UPDATE OR DELETE ON documents
  FOR EACH ROW EXECUTE FUNCTION notify_document_change();

-- Mirror of 006_kb_sharing.sql so the test DB reflects the live schema.
CREATE TYPE kb_visibility AS ENUM ('private', 'shared', 'public');

ALTER TABLE knowledge_bases
    ADD COLUMN visibility kb_visibility NOT NULL DEFAULT 'private',
    ADD COLUMN public_slug TEXT,
    ADD COLUMN share_token TEXT NOT NULL DEFAULT replace(gen_random_uuid()::text, '-', ''),
    ADD COLUMN visibility_updated_at TIMESTAMPTZ,
    ADD COLUMN published_at TIMESTAMPTZ,
    ADD CONSTRAINT knowledge_bases_public_slug_format
        CHECK (public_slug IS NULL OR public_slug ~ '^[a-z0-9][a-z0-9-]{0,78}[a-z0-9]$'),
    ADD CONSTRAINT knowledge_bases_public_requires_slug
        CHECK (visibility <> 'public' OR public_slug IS NOT NULL);

CREATE UNIQUE INDEX idx_knowledge_bases_public_slug
    ON knowledge_bases (public_slug)
    WHERE public_slug IS NOT NULL;

CREATE UNIQUE INDEX idx_knowledge_bases_share_token
    ON knowledge_bases (share_token);

CREATE INDEX idx_knowledge_bases_public_lookup
    ON knowledge_bases (public_slug, updated_at)
    WHERE visibility = 'public';

-- Mirror of 010_knowledge_base_events.sql (minus the anon role, which the
-- test database does not create). The backfill statements stay executable
-- here; the test schema is empty, so fixtures start without synthetic history.

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
    FROM PUBLIC, authenticated;

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

-- Mirrors supabase/migrations/011_performance.sql (PGroonga index omitted above).
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
DROP INDEX idx_documents_tags;
DROP INDEX idx_documents_date;
DROP INDEX idx_knowledge_bases_public_lookup;
