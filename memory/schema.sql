-- LLM Wiki — bi-temporal MEMORY index schema (SQLite + FTS5 + sqlite-vec).
--
-- This database (.llmwiki/memory.db) is SEPARATE from the wiki index (.llmwiki/index.db)
-- and is owned entirely by the standalone memory MCP server. It is derived state —
-- deletable and rebuildable from the append-only JSONL under wiki/.memory/.
--
-- The vec0 virtual table (claim_vec) is created in store.py after the sqlite-vec
-- extension is loaded (it cannot live in this file).

PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=30000;
PRAGMA foreign_keys=ON;

-- Episodes: append-only structured record of each decision/write event.
-- The queryable, semantic replacement for wiki/log.md. NEVER updated, NEVER deleted.
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    kind TEXT NOT NULL CHECK (kind IN ('ingest','query','decision','revision','lint','consolidation')),
    summary TEXT NOT NULL,                                  -- one-line "what happened"
    detail TEXT,                                            -- "why / context / subtleties"
    source_path TEXT,
    source_document_id TEXT,
    actor TEXT NOT NULL DEFAULT 'claude',                   -- claude | consolidation | user
    occurred_at TEXT NOT NULL DEFAULT (datetime('now')),    -- valid time (when it happened in the world)
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),    -- transaction time (when system learned it)
    metadata TEXT,                                          -- JSON blob
    content_hash TEXT                                       -- idempotent-rebuild guard
);

-- Claims: bi-temporal facts AND decisions. Append-only — supersession closes a row, never overwrites.
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    claim_type TEXT NOT NULL DEFAULT 'fact' CHECK (claim_type IN ('fact','decision','preference','observation')),
    subject TEXT,                                           -- grouping key (entity/topic)
    statement TEXT NOT NULL,                                -- the fact/decision, natural language
    rationale TEXT,                                         -- the "why" — context & subtleties
    confidence REAL DEFAULT 1.0,

    -- Bi-temporal columns (Zep/Graphiti + Fowler): 4 timestamps
    valid_at TEXT NOT NULL DEFAULT (datetime('now')),       -- true-in-world start
    invalid_at TEXT,                                        -- true-in-world end (NULL = still true)
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),    -- system learned it
    expired_at TEXT,                                        -- system retired it (NULL = current belief)

    -- Supersession links (append-only; old row stays queryable)
    superseded_by TEXT REFERENCES claims(id),
    supersedes TEXT REFERENCES claims(id),

    -- Provenance
    episode_id TEXT REFERENCES episodes(id),
    source_path TEXT,
    source_document_id TEXT,

    content_hash TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- FTS5 over claim statement + rationale (mirrors chunks_fts in the wiki schema)
CREATE VIRTUAL TABLE IF NOT EXISTS claim_fts USING fts5(
    statement,
    rationale,
    content='claims',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS claim_fts_insert AFTER INSERT ON claims BEGIN
    INSERT INTO claim_fts(rowid, statement, rationale) VALUES (new.rowid, new.statement, new.rationale);
END;

CREATE TRIGGER IF NOT EXISTS claim_fts_delete AFTER DELETE ON claims BEGIN
    INSERT INTO claim_fts(claim_fts, rowid, statement, rationale) VALUES('delete', old.rowid, old.statement, old.rationale);
END;

CREATE TRIGGER IF NOT EXISTS claim_fts_update AFTER UPDATE ON claims BEGIN
    INSERT INTO claim_fts(claim_fts, rowid, statement, rationale) VALUES('delete', old.rowid, old.statement, old.rationale);
    INSERT INTO claim_fts(rowid, statement, rationale) VALUES (new.rowid, new.statement, new.rationale);
END;

-- Uncertain auto-decisions escalated to the user (AskUserQuestion-shaped)
CREATE TABLE IF NOT EXISTS clarifications (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    origin TEXT NOT NULL CHECK (origin IN ('ingestion','consolidation')),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','dismissed')),
    question TEXT NOT NULL,                                 -- prompt shown to the user
    options TEXT NOT NULL,                                  -- JSON: {options:[{label,description,action}], recommended:int}
    candidate_claim_ids TEXT NOT NULL,                      -- JSON list of affected claim ids
    proposed_action TEXT,                                   -- assessor best guess: add|supersede|merge|noop
    confidence REAL,
    uncertainty_reasons TEXT,                               -- JSON list
    resolution TEXT,
    resolved_by TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    content_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_claims_subject ON claims(subject);
CREATE INDEX IF NOT EXISTS idx_claims_current ON claims(expired_at, invalid_at);
CREATE INDEX IF NOT EXISTS idx_claims_supersedes ON claims(supersedes);
CREATE INDEX IF NOT EXISTS idx_claims_superseded_by ON claims(superseded_by);
CREATE INDEX IF NOT EXISTS idx_episodes_occurred ON episodes(occurred_at);
CREATE INDEX IF NOT EXISTS idx_episodes_source_path ON episodes(source_path);
CREATE INDEX IF NOT EXISTS idx_clarifications_status ON clarifications(status);

-- "Quick memory" = current, valid, non-superseded facts/decisions
CREATE VIEW IF NOT EXISTS current_claims AS
    SELECT * FROM claims WHERE expired_at IS NULL AND invalid_at IS NULL;
