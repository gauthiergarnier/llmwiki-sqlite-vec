ALTER TABLE knowledge_bases
    ADD COLUMN kind text NOT NULL DEFAULT 'wiki'
    CHECK (kind IN ('wiki', 'course'));
