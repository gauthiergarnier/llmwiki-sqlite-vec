-- Backfill activity events for workspaces that predate event tracking.
-- Creation facts are known; updated_at is not reliable edit history, so no
-- historical update events are synthesized.

INSERT OR IGNORE INTO knowledge_base_events
    (knowledge_base_id, user_id, event_type, subject_kind, subject_title,
     event_key, occurred_at)
SELECT id, user_id, 'wiki.created', 'wiki', name,
       'kb:' || id || ':created', created_at
FROM workspace;

INSERT OR IGNORE INTO knowledge_base_events
    (knowledge_base_id, user_id, event_type, subject_kind, document_id,
     document_number, document_version, subject_title, subject_path,
     event_key, metadata, occurred_at)
SELECT (SELECT id FROM workspace LIMIT 1), d.user_id,
       CASE WHEN d.source_kind = 'wiki' THEN 'page.created' ELSE 'source.added' END,
       CASE WHEN d.source_kind = 'wiki' THEN 'wiki_page' ELSE 'source' END,
       d.id, d.document_number, d.version,
       COALESCE(NULLIF(d.title, ''), d.filename), d.path || d.filename,
       'doc:' || d.id || ':created',
       json_object('file_type', d.file_type, 'file_size', d.file_size), d.created_at
FROM documents d
WHERE d.source_kind <> 'asset'
  AND COALESCE(json_extract(d.metadata, '$.hidden'), 0) = 0
  AND COALESCE(json_extract(d.metadata, '$.asset'), 0) = 0
  AND NOT (d.path = '/wiki/' AND d.filename IN ('index.json', 'log.md', 'overview.md'))
ORDER BY d.created_at, d.id;

INSERT OR IGNORE INTO knowledge_base_events
    (knowledge_base_id, user_id, event_type, subject_kind, subject_title, event_key)
SELECT id, user_id, 'tracking.started', 'wiki', name,
       'kb:' || id || ':tracking-started'
FROM workspace;
