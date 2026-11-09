"""Fork: shared/chunk_vectors.py keeps chunk_vec in step with document_chunks."""

import sqlite3
import uuid

import pytest
from infra.db.local_migrations import apply_migrations

from tests.support import fake_embedder

pytest.importorskip("sqlite_vec")

import chunk_vectors  # noqa: E402  (shared/ on sys.path via fake_embedder)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    fake_embedder.install(monkeypatch)
    path = str(tmp_path / "index.db")
    apply_migrations(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO workspace (id, name, description, user_id) VALUES ('ws', 'ws', '', 'u')"
    )
    conn.commit()
    conn.close()
    return path


def _add_doc(path: str, chunks: list[str], *, annotated: str | None = None) -> str:
    doc_id = str(uuid.uuid4())
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO documents (id, user_id, filename, path, relative_path, source_kind, file_type, status) "
        "VALUES (?, 'u', ?, '/wiki/', ?, 'wiki', 'md', 'ready')",
        (doc_id, f"{doc_id}.md", f"wiki/{doc_id}.md"),
    )
    for i, text in enumerate(chunks):
        conn.execute(
            "INSERT INTO document_chunks (document_id, chunk_index, content, source_content, token_count) "
            "VALUES (?, ?, ?, ?, 5)",
            (doc_id, i, annotated or text, text),
        )
    conn.commit()
    conn.close()
    return doc_id


def _vec_conn(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    assert chunk_vectors.load_sqlite_vec(conn)
    return conn


def test_embeds_missing_then_is_idempotent(db_path):
    _add_doc(db_path, ["The car broke down.", "Budget review."])

    first = chunk_vectors.sync_chunk_vectors(db_path)
    assert first == {"removed": 0, "embedded": 2, "total_chunks": 2, "enabled": True}

    second = chunk_vectors.sync_chunk_vectors(db_path)
    assert second["embedded"] == 0 and second["removed"] == 0


def test_drops_vectors_of_deleted_chunks(db_path):
    doc_id = _add_doc(db_path, ["one car", "two cars", "three vehicles"])
    chunk_vectors.sync_chunk_vectors(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))  # cascades to chunks, not vec0
    conn.commit()
    conn.close()

    result = chunk_vectors.sync_chunk_vectors(db_path)
    assert result["removed"] == 3
    assert _vec_conn(db_path).execute("SELECT count(*) FROM chunk_vec").fetchone()[0] == 0


def test_replaced_chunks_are_re_embedded(db_path):
    doc_id = _add_doc(db_path, ["old text about cars"])
    chunk_vectors.sync_chunk_vectors(db_path)

    # Upstream replaces a document's chunks wholesale on every edit (new chunk ids).
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (doc_id,))
    conn.execute(
        "INSERT INTO document_chunks (document_id, chunk_index, content, source_content, token_count) "
        "VALUES (?, 0, 'new text about pricing', 'new text about pricing', 5)",
        (doc_id,),
    )
    conn.commit()
    conn.close()

    result = chunk_vectors.sync_chunk_vectors(db_path)
    assert result["removed"] == 1 and result["embedded"] == 1
    vc = _vec_conn(db_path)
    vec_ids = {r[0] for r in vc.execute("SELECT chunk_id FROM chunk_vec")}
    chunk_ids = {r[0] for r in vc.execute("SELECT id FROM document_chunks")}
    assert vec_ids == chunk_ids


def test_embeds_source_content_not_annotated_content(db_path, monkeypatch):
    seen: list[str] = []
    real = fake_embedder.fake_embed
    import embedder

    monkeypatch.setattr(embedder, "embed_texts", lambda texts: seen.extend(texts) or [real(t) for t in texts])
    _add_doc(db_path, ["raw source text"], annotated="raw source text\n\n[^h1]: my highlight note")

    chunk_vectors.sync_chunk_vectors(db_path)
    assert seen == ["raw source text"]


def test_request_is_noop_without_a_running_syncer():
    chunk_vectors.request_vector_sync()  # must not raise


def test_start_respects_disable_switch(monkeypatch, db_path):
    import asyncio

    monkeypatch.setenv("LLMWIKI_VECTOR_SYNC", "0")

    async def run():
        chunk_vectors.start_vector_sync(db_path)
        assert chunk_vectors._syncer is None

    asyncio.run(run())


def test_syncer_retries_soon_and_quietly_when_index_is_locked(monkeypatch, caplog):
    """A long writer (e.g. `llmwiki reindex`) must not cost a traceback or a 5-minute wait."""
    import asyncio
    import logging

    calls = []

    def fake_sync(db_path, **_):
        calls.append(db_path)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return {"removed": 0, "embedded": 0, "total_chunks": 0, "enabled": True}

    monkeypatch.setattr(chunk_vectors, "sync_chunk_vectors", fake_sync)
    monkeypatch.setattr(chunk_vectors, "_LOCK_RETRY_S", 0.05)

    async def run():
        syncer = chunk_vectors._VectorSyncer("x.db", debounce=0, interval=3600)
        for _ in range(100):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.01)
        syncer.task.cancel()

    with caplog.at_level(logging.WARNING, logger=chunk_vectors.logger.name):
        asyncio.run(run())

    assert len(calls) == 2  # retried well before the 3600s sweep
    busy = [r for r in caplog.records if "index busy" in r.getMessage()]
    assert len(busy) == 1 and busy[0].exc_info is None
