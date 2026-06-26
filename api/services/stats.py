"""Index / search / reference-graph stats for the local workspace.

All SQL lives here; the route is a thin layer (see routes/local_stats.py).
"""


async def _count(db, sql: str, params=()) -> int:
    cursor = await db.execute(sql, params)
    row = await cursor.fetchone()
    return row[0] if row and row[0] is not None else 0


async def get_index_stats(db, user_id: str) -> dict:
    """Return index, search, and graph metrics for the (single) local workspace."""
    # Embedding model constants — imported lazily so module load doesn't depend
    # on shared/ being on sys.path yet (it is by request time).
    from embedder import MODEL_NAME, EMBEDDING_DIM

    docs_total = await _count(
        db, "SELECT count(*) FROM documents WHERE user_id = ? AND status != 'failed'", (user_id,)
    )
    wiki = await _count(
        db,
        "SELECT count(*) FROM documents WHERE user_id = ? AND status != 'failed' AND source_kind = 'wiki'",
        (user_id,),
    )
    sources = docs_total - wiki

    chunks = await _count(db, "SELECT count(*) FROM document_chunks")
    embeddings = await _count(db, "SELECT count(*) FROM chunk_vec")
    fts_rows = await _count(db, "SELECT count(*) FROM chunks_fts")

    references = await _count(db, "SELECT count(*) FROM document_references")
    cites = await _count(db, "SELECT count(*) FROM document_references WHERE reference_type = 'cites'")
    links = await _count(db, "SELECT count(*) FROM document_references WHERE reference_type = 'links_to'")
    sources_connected = await _count(
        db,
        "SELECT count(DISTINCT dr.target_document_id) FROM document_references dr "
        "JOIN documents t ON dr.target_document_id = t.id "
        "WHERE dr.reference_type = 'cites' AND t.source_kind != 'wiki'",
    )

    return {
        "documents": {"total": docs_total, "wiki_pages": wiki, "sources": sources},
        "search": {
            "chunks": chunks,
            "embeddings": embeddings,
            "fts_rows": fts_rows,
            "embedding_model": MODEL_NAME,
            "embedding_dim": EMBEDDING_DIM,
            "enabled": chunks > 0,
        },
        "graph": {
            "references": references,
            "cites": cites,
            "links": links,
            "sources_connected": sources_connected,
            "sources_orphan": max(0, sources - sources_connected),
        },
    }
