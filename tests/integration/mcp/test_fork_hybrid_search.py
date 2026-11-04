"""Fork: hybrid (FTS5 + sqlite-vec) search in SqliteVaultFS, with a deterministic fake embedder."""

import os

import pytest

pytest.importorskip("sqlite_vec")

from tests.support import fake_embedder  # noqa: E402


@pytest.fixture
async def hybrid_fs(workspace, monkeypatch):
    fake_embedder.install(monkeypatch)
    from vaultfs.sqlite import SqliteVaultFS

    from tests.integration.mcp.conftest import TEST_USER_ID

    await SqliteVaultFS.close()
    await SqliteVaultFS.init(str(workspace))
    fs = SqliteVaultFS(TEST_USER_ID)
    kb_id = await fs.ensure_workspace("hybrid")
    db_path = os.path.join(str(workspace), ".llmwiki", "index.db")
    yield fs, kb_id, db_path
    await SqliteVaultFS.close()


async def _seed(fs, kb_id, db_path):
    import chunk_vectors

    await fs.create_document(
        kb_id, "fleet.md", "Fleet", "/wiki/", "md",
        "The company car broke down twice this quarter.", [],
    )
    await fs.create_document(
        kb_id, "money.md", "Money", "/wiki/", "md",
        "Pricing discussion with finance about next year.", [],
    )
    return chunk_vectors.sync_chunk_vectors(db_path)


async def test_semantic_match_found_when_keywords_miss(hybrid_fs):
    fs, kb_id, db_path = hybrid_fs
    result = await _seed(fs, kb_id, db_path)
    assert result["embedded"] >= 2

    hits = await fs.search_chunks(kb_id, "automobile", limit=5)
    assert hits, "vector search should find the car page although 'automobile' never appears"
    assert hits[0]["filename"] == "fleet.md"
    assert hits[0]["source_hit"] is False


async def test_keyword_and_vector_agree_ranks_first(hybrid_fs):
    fs, kb_id, db_path = hybrid_fs
    await _seed(fs, kb_id, db_path)

    hits = await fs.search_chunks(kb_id, "pricing", limit=5)
    assert hits[0]["filename"] == "money.md"
    assert hits[0]["source_hit"] is True
    assert 0 < hits[0]["score"] <= 100


async def test_falls_back_to_keywords_without_embeddings(hybrid_fs):
    fs, kb_id, _db_path = hybrid_fs
    await fs.create_document(kb_id, "fleet.md", "Fleet", "/wiki/", "md", "The car broke down.", [])
    # No sync → chunk_vec empty → keyword-only, like upstream.
    assert [h["filename"] for h in await fs.search_chunks(kb_id, "car", limit=5)] == ["fleet.md"]
    assert await fs.search_chunks(kb_id, "automobile", limit=5) == []


async def test_annotations_scope_stays_keyword_only(hybrid_fs):
    fs, kb_id, db_path = hybrid_fs
    await _seed(fs, kb_id, db_path)
    assert await fs.search_chunks(kb_id, "automobile", limit=5, scope="annotations") == []


async def test_source_scope_keeps_semantic_hits(hybrid_fs):
    fs, kb_id, db_path = hybrid_fs
    await _seed(fs, kb_id, db_path)
    hits = await fs.search_chunks(kb_id, "automobile", limit=5, scope="source")
    assert [h["filename"] for h in hits][:1] == ["fleet.md"]


async def test_edit_reembeds_and_drops_stale_vectors(hybrid_fs):
    import chunk_vectors

    fs, kb_id, db_path = hybrid_fs
    await _seed(fs, kb_id, db_path)
    doc = await fs.get_document(kb_id, "fleet.md", "/wiki/")
    await fs.update_document(doc["id"], "Partner alliance kickoff with the reseller.")

    result = chunk_vectors.sync_chunk_vectors(db_path)
    assert result["removed"] >= 1 and result["embedded"] >= 1

    hits = await fs.search_chunks(kb_id, "partners", limit=5)
    assert hits and hits[0]["filename"] == "fleet.md"
    # Vector set mirrors the chunk set exactly — the old "car" chunk's vector is gone.
    from vaultfs.sqlite import SqliteVaultFS
    db = SqliteVaultFS._db_or_raise()
    vec_ids = {r[0] for r in await (await db.execute("SELECT chunk_id FROM chunk_vec")).fetchall()}
    chunk_ids = {r[0] for r in await (await db.execute("SELECT id FROM document_chunks")).fetchall()}
    assert vec_ids == chunk_ids
