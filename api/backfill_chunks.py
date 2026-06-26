"""Backfill document_chunks + chunk_vec embeddings for text documents.

The local processor (domain/local_processor.py) only chunks PDF / office /
spreadsheet / HTML; markdown and plain-text documents — the bulk of a wiki —
are stored with content but no chunks, so the hybrid search (FTS5 + sqlite-vec)
has nothing to match. This rebuilds chunks + embeddings for every document that
has text content (or already-extracted pages), reusing the canonical chunker and
the embed/insert path from the local processor.

Run from the api/ directory (or with api/ on PYTHONPATH):

    python -m backfill_chunks /path/to/workspace
"""
import asyncio
import sys
from pathlib import Path

import aiosqlite
import sqlite_vec

# shared/ holds the embedder; mirror local_processor's path setup so the
# `from embedder import ...` inside _store_chunks (and below) resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from services.chunker import chunk_text, chunk_pages
from domain.local_processor import _store_chunks
from embedder import EMBEDDING_DIM


async def backfill(workspace: str) -> tuple[int, int]:
    ws = Path(workspace).resolve()
    db_path = ws / ".llmwiki" / "index.db"
    if not db_path.exists():
        raise SystemExit(f"No index at {db_path}")

    db = await aiosqlite.connect(str(db_path))
    try:
        await db.enable_load_extension(True)
        await db.load_extension(sqlite_vec.loadable_path())
        await db.enable_load_extension(False)
        await db.execute("PRAGMA busy_timeout=30000")
        await db.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0("
            f"chunk_id text primary key, embedding float[{EMBEDDING_DIM}])"
        )
        # Full rebuild: clear existing chunks + embeddings up front so re-runs are
        # idempotent and chunk_vec (which has no FK cascade) doesn't accumulate
        # orphaned vectors across reindexes.
        await db.execute("DELETE FROM document_chunks")
        await db.execute("DELETE FROM chunk_vec")
        await db.commit()

        cur = await db.execute(
            "SELECT id, content FROM documents WHERE status != 'failed'"
        )
        rows = await cur.fetchall()

        n_docs = n_chunks = 0
        for doc_id, content in rows:
            pcur = await db.execute(
                "SELECT page, content FROM document_pages WHERE document_id = ? ORDER BY page",
                (doc_id,),
            )
            pages = await pcur.fetchall()
            if pages:
                chunks = chunk_pages([(p, c) for p, c in pages])
            elif content and content.strip():
                chunks = chunk_text(content)
            else:
                continue
            if not chunks:
                continue
            await _store_chunks(db, doc_id, chunks)  # deletes old, inserts chunks + embeddings
            n_docs += 1
            n_chunks += len(chunks)
        return n_docs, n_chunks
    finally:
        await db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m backfill_chunks <workspace>")
    docs, chunks = asyncio.run(backfill(sys.argv[1]))
    print(f"  ✓ Chunked {docs} documents ({chunks} chunks + embeddings)")
