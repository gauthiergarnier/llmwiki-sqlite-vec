"""Finish a `llmwiki reindex` so the index is fully usable without starting the server.

Fork addition. Upstream's reindex only re-inserts document rows; chunking happens
later in the API's startup reconcile, and the reference graph is left empty. This
runs, in the api/ import context:

1. ``reconcile_workspace`` — upstream's own backfill: chunk text/markdown docs and
   extract PDFs/office/spreadsheets that have no chunks yet;
2. ``rebuild_local`` — rebuild the citation/link graph against the new document ids;
3. ``sync_chunk_vectors`` — embed every chunk for hybrid (keyword + vector) search.

Run from api/ (the CLI does this in a subprocess because api/ and mcp/ both have
top-level packages named ``config``/``services`` that would collide):

    python -m reindex_finish /path/to/workspace
"""

import asyncio
import logging
import sys
from pathlib import Path


async def _finish(ws: Path) -> int:
    from infra.db.sqlite import create_pool

    db_path = ws / ".llmwiki" / "index.db"
    if not db_path.exists():
        print(f"No index at {db_path}", file=sys.stderr)
        return 1

    from chunk_vectors import sync_chunk_vectors  # shared/ is on sys.path via infra.db.sqlite
    from domain.local_processor import reconcile_workspace
    from services.graph import rebuild_local

    db = await create_pool(str(db_path))
    try:
        cursor = await db.execute("SELECT count(*) FROM document_chunks")
        before = (await cursor.fetchone())[0]
        print("  Chunking documents…", flush=True)
        await reconcile_workspace(db, ws)
        cursor = await db.execute(
            "SELECT count(*), count(DISTINCT document_id) FROM document_chunks"
        )
        chunks, docs = await cursor.fetchone()
        print(f"  ✓ Chunked {docs} documents ({chunks - before} new chunks, {chunks} total)")

        cursor = await db.execute("SELECT user_id FROM workspace LIMIT 1")
        row = await cursor.fetchone()
        if row:
            graph = await rebuild_local(db, row[0])
            print(
                f"  ✓ Reference graph rebuilt ({graph.get('citations', 0)} citations, "
                f"{graph.get('links', 0)} links)"
            )
    finally:
        await db.close()

    result = await asyncio.to_thread(sync_chunk_vectors, str(db_path), progress=True)
    if result["enabled"]:
        print(
            f"  ✓ Embeddings in sync ({result['embedded']} new, "
            f"{result['removed']} stale removed, {result['total_chunks']} chunks)"
        )
    else:
        print("  (embeddings skipped — sqlite-vec unavailable; search is keyword-only)", file=sys.stderr)
    return 0


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m reindex_finish <workspace>", file=sys.stderr)
        sys.exit(2)
    logging.basicConfig(level=logging.WARNING)
    sys.exit(asyncio.run(_finish(Path(sys.argv[1]).resolve())))


if __name__ == "__main__":
    main()
