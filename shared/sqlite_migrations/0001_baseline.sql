-- Baseline schema as of 2026-08-14. Never edit — append numbered migrations instead.
-- The index is derived state: deletable and rebuildable from the workspace filesystem.

CREATE TABLE IF NOT EXISTS workspace (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'wiki',
    user_id TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id)
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    title TEXT,
    path TEXT DEFAULT '/' NOT NULL,
    relative_path TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('wiki', 'source', 'asset')),
    file_type TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    document_number INTEGER,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'ready', 'failed')),
    page_count INTEGER,
    content TEXT,
    tags TEXT DEFAULT '[]',
    date TEXT,
    metadata TEXT,
    error_message TEXT,
    version INTEGER DEFAULT 0,
    parser TEXT,
    content_hash TEXT,
    mtime_ns INTEGER,
    last_indexed_at TEXT,
    stale_since TEXT,
    highlights TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(relative_path)
);

CREATE TABLE IF NOT EXISTS knowledge_base_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_base_id TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'tracking.started', 'wiki.created',
        'page.created', 'page.updated', 'page.archived', 'page.restored', 'page.deleted',
        'source.added', 'source.updated', 'source.deleted'
    )),
    subject_kind TEXT NOT NULL CHECK (subject_kind IN ('wiki', 'wiki_page', 'source')),
    document_id TEXT,
    document_number INTEGER,
    document_version INTEGER,
    subject_title TEXT NOT NULL,
    subject_path TEXT,
    event_key TEXT UNIQUE,
    metadata TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS document_pages (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    content TEXT NOT NULL,
    elements TEXT,
    UNIQUE(document_id, page)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    -- `content` is the materialized form (source + annotations) used by FTS.
    -- `source_content` is the immutable raw chunk text; `annotations_text`
    -- holds the materialized footnote-body block of highlights/comments
    -- touching this chunk, maintained by the highlight CRUD service methods.
    -- See docs/highlights-in-search-spec.md.
    content TEXT NOT NULL,
    source_content TEXT NOT NULL DEFAULT '',
    annotations_text TEXT,
    has_highlight INTEGER NOT NULL DEFAULT 0,
    page INTEGER,
    start_char INTEGER,
    token_count INTEGER NOT NULL,
    header_breadcrumb TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS document_references (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    source_document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    target_document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    reference_type TEXT NOT NULL CHECK (reference_type IN ('cites', 'links_to')),
    page INTEGER,
    UNIQUE(source_document_id, target_document_id, reference_type)
);

-- FTS5 full-text search (replaces pgroonga)
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    content='document_chunks',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

-- Keep FTS in sync with document_chunks
CREATE TRIGGER IF NOT EXISTS chunks_fts_insert AFTER INSERT ON document_chunks BEGIN
    INSERT INTO chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_delete AFTER DELETE ON document_chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_update AFTER UPDATE ON document_chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
    INSERT INTO chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE INDEX IF NOT EXISTS idx_documents_relative_path ON documents(relative_path);
CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(path);
CREATE INDEX IF NOT EXISTS idx_documents_source_kind ON documents(source_kind);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_kb_events_feed
  ON knowledge_base_events(knowledge_base_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_kb_events_user
  ON knowledge_base_events(user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(document_id);
-- Partial index for the "search but only chunks I've annotated" filter.
CREATE INDEX IF NOT EXISTS idx_chunks_annotated
  ON document_chunks(document_id) WHERE has_highlight = 1;
CREATE INDEX IF NOT EXISTS idx_refs_source ON document_references(source_document_id);
CREATE INDEX IF NOT EXISTS idx_refs_target ON document_references(target_document_id);

CREATE TRIGGER IF NOT EXISTS knowledge_base_activity_insert
AFTER INSERT ON workspace
BEGIN
    INSERT OR IGNORE INTO knowledge_base_events (
        knowledge_base_id, user_id, event_type, subject_kind,
        subject_title, event_key, occurred_at
    ) VALUES (
        NEW.id, NEW.user_id, 'wiki.created', 'wiki',
        NEW.name, 'kb:' || NEW.id || ':created', NEW.created_at
    );
END;

CREATE TRIGGER IF NOT EXISTS document_activity_insert
AFTER INSERT ON documents
WHEN NEW.source_kind <> 'asset'
  AND COALESCE(json_extract(NEW.metadata, '$.hidden'), 0) = 0
  AND COALESCE(json_extract(NEW.metadata, '$.asset'), 0) = 0
  AND NOT (NEW.path = '/wiki/' AND NEW.filename IN ('index.json', 'log.md', 'overview.md'))
BEGIN
    INSERT OR IGNORE INTO knowledge_base_events (
        knowledge_base_id, user_id, event_type, subject_kind,
        document_id, document_number, document_version,
        subject_title, subject_path, event_key, metadata, occurred_at
    ) VALUES (
        (SELECT id FROM workspace LIMIT 1),
        NEW.user_id,
        CASE WHEN NEW.source_kind = 'wiki' THEN 'page.created' ELSE 'source.added' END,
        CASE WHEN NEW.source_kind = 'wiki' THEN 'wiki_page' ELSE 'source' END,
        NEW.id,
        NEW.document_number,
        NEW.version,
        COALESCE(NULLIF(NEW.title, ''), NEW.filename),
        NEW.path || NEW.filename,
        'doc:' || NEW.id || ':created',
        json_object('file_type', NEW.file_type, 'file_size', NEW.file_size),
        NEW.created_at
    );
END;

CREATE TRIGGER IF NOT EXISTS document_activity_update
AFTER UPDATE ON documents
WHEN NEW.source_kind <> 'asset'
  AND COALESCE(json_extract(NEW.metadata, '$.hidden'), 0) = 0
  AND COALESCE(json_extract(NEW.metadata, '$.asset'), 0) = 0
  AND NOT (NEW.path = '/wiki/' AND NEW.filename IN ('index.json', 'log.md'))
  AND (
      (
          OLD.content IS NOT NEW.content
          AND NOT (
              OLD.source_kind <> 'wiki'
              AND OLD.content IS NULL
              AND OLD.status IN ('pending', 'processing')
              AND NEW.status = 'ready'
          )
      )
      OR OLD.filename IS NOT NEW.filename
      OR OLD.title IS NOT NEW.title
      OR OLD.path IS NOT NEW.path
      OR OLD.tags IS NOT NEW.tags
      OR OLD.date IS NOT NEW.date
      OR json_extract(OLD.metadata, '$.properties') IS NOT json_extract(NEW.metadata, '$.properties')
  )
BEGIN
    INSERT INTO knowledge_base_events (
        knowledge_base_id, user_id, event_type, subject_kind,
        document_id, document_number, document_version,
        subject_title, subject_path, metadata
    ) VALUES (
        (SELECT id FROM workspace LIMIT 1),
        NEW.user_id,
        CASE WHEN NEW.source_kind = 'wiki' THEN 'page.updated' ELSE 'source.updated' END,
        CASE WHEN NEW.source_kind = 'wiki' THEN 'wiki_page' ELSE 'source' END,
        NEW.id,
        NEW.document_number,
        NEW.version,
        COALESCE(NULLIF(NEW.title, ''), NEW.filename),
        NEW.path || NEW.filename,
        json_object(
            'changes', json(
                '[' || rtrim(
                    CASE WHEN OLD.content IS NOT NEW.content
                        AND NOT (
                            OLD.source_kind <> 'wiki'
                            AND OLD.content IS NULL
                            AND OLD.status IN ('pending', 'processing')
                            AND NEW.status = 'ready'
                        ) THEN '"content",' ELSE '' END
                    || CASE WHEN OLD.filename IS NOT NEW.filename OR OLD.title IS NOT NEW.title
                        THEN '"title",' ELSE '' END
                    || CASE WHEN OLD.path IS NOT NEW.path THEN '"path",' ELSE '' END
                    || CASE WHEN OLD.tags IS NOT NEW.tags THEN '"tags",' ELSE '' END
                    || CASE WHEN OLD.date IS NOT NEW.date THEN '"date",' ELSE '' END
                    || CASE WHEN json_extract(OLD.metadata, '$.properties') IS NOT json_extract(NEW.metadata, '$.properties')
                        THEN '"properties",' ELSE '' END,
                    ','
                ) || ']'
            ),
            'file_type', NEW.file_type,
            'file_size', NEW.file_size
        )
    );
END;

CREATE TRIGGER IF NOT EXISTS document_activity_delete
AFTER DELETE ON documents
WHEN OLD.source_kind <> 'asset'
  AND EXISTS (SELECT 1 FROM workspace LIMIT 1)
  AND COALESCE(json_extract(OLD.metadata, '$.hidden'), 0) = 0
  AND COALESCE(json_extract(OLD.metadata, '$.asset'), 0) = 0
  AND NOT (OLD.path = '/wiki/' AND OLD.filename IN ('index.json', 'log.md'))
BEGIN
    INSERT INTO knowledge_base_events (
        knowledge_base_id, user_id, event_type, subject_kind,
        document_id, document_number, document_version,
        subject_title, subject_path, metadata
    ) VALUES (
        (SELECT id FROM workspace LIMIT 1),
        OLD.user_id,
        CASE WHEN OLD.source_kind = 'wiki' THEN 'page.deleted' ELSE 'source.deleted' END,
        CASE WHEN OLD.source_kind = 'wiki' THEN 'wiki_page' ELSE 'source' END,
        OLD.id,
        OLD.document_number,
        OLD.version,
        COALESCE(NULLIF(OLD.title, ''), OLD.filename),
        OLD.path || OLD.filename,
        json_object('file_type', OLD.file_type, 'file_size', OLD.file_size)
    );
END;
