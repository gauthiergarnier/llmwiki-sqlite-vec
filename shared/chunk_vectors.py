"""Keep the sqlite-vec ``chunk_vec`` index in step with ``document_chunks``.

Fork addition (hybrid search). Upstream writes chunks from many places — ingest,
the file watcher, MCP create/edit/append, highlight rewrites — and replaces them
wholesale on every edit. Rather than embedding at each call site, this module
*reconciles* the two tables:

- vectors whose chunk no longer exists are dropped (``chunk_vec`` is a vec0
  virtual table, so there is no FK cascade to do it for us);
- chunks without a vector are embedded from ``source_content`` (the immutable
  raw chunk text — ``content`` also carries highlight annotations).

``sync_chunk_vectors`` is idempotent, safe to run concurrently from the API, MCP
and CLI processes (inserts happen under ``BEGIN IMMEDIATE`` with a presence
check), and cheap when there is nothing to do (two id scans).

``start_vector_sync`` runs it in the background of a long-lived process:
immediately at start, shortly after each ``request_vector_sync()`` (debounced),
and on a slow periodic sweep as a safety net. Search degrades gracefully to
keyword-only for chunks that are not embedded yet.

Stdlib + sqlite_vec only at import time; the embedding model loads lazily.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sqlite3
import time

from embedder import EMBEDDING_DIM

logger = logging.getLogger(__name__)

VEC_TABLE_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0("
    f"chunk_id text primary key, embedding float[{EMBEDDING_DIM}])"
)

_BATCH = 64
_BUSY_TIMEOUT_MS = 60_000
_LOCK_RETRY_S = 15.0


def _is_lock_error(exc: sqlite3.OperationalError) -> bool:
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


# ── Extension loading ──────────────────────────────────────────────────────

def load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """Load sqlite-vec into a stdlib connection. Returns False if unavailable."""
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:
        logger.warning("sqlite-vec unavailable — vector search disabled", exc_info=True)
        return False


async def load_sqlite_vec_async(db) -> bool:
    """Load sqlite-vec into an aiosqlite connection and ensure ``chunk_vec`` exists."""
    try:
        import sqlite_vec

        await db.enable_load_extension(True)
        await db.load_extension(sqlite_vec.loadable_path())
        await db.enable_load_extension(False)
        await db.execute(VEC_TABLE_DDL)
        await db.commit()
        return True
    except Exception:
        logger.warning("sqlite-vec unavailable — vector search disabled", exc_info=True)
        return False


# ── Reconciliation ─────────────────────────────────────────────────────────

def sync_chunk_vectors(db_path: str, *, progress: bool = False) -> dict:
    """Make ``chunk_vec`` mirror ``document_chunks``. Blocking; run off the event loop.

    Returns counts: {"removed", "embedded", "total_chunks", "enabled"}.
    """
    result = {"removed": 0, "embedded": 0, "total_chunks": 0, "enabled": False}
    conn = sqlite3.connect(db_path, timeout=_BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    try:
        conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        if not load_sqlite_vec(conn):
            return result
        conn.execute(VEC_TABLE_DDL)
        result["enabled"] = True

        chunk_ids = {r[0] for r in conn.execute("SELECT id FROM document_chunks")}
        vec_ids = {r[0] for r in conn.execute("SELECT chunk_id FROM chunk_vec")}
        result["total_chunks"] = len(chunk_ids)

        orphans = vec_ids - chunk_ids
        if orphans:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.executemany("DELETE FROM chunk_vec WHERE chunk_id = ?", [(i,) for i in orphans])
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            result["removed"] = len(orphans)

        missing = sorted(chunk_ids - vec_ids)
        if not missing:
            return result

        from embedder import embed_texts, serialize_embedding

        started = time.monotonic()
        for start in range(0, len(missing), _BATCH):
            batch = missing[start:start + _BATCH]
            placeholders = ",".join("?" * len(batch))
            rows = conn.execute(
                "SELECT id, COALESCE(NULLIF(source_content, ''), content) "
                f"FROM document_chunks WHERE id IN ({placeholders})",
                batch,
            ).fetchall()
            if not rows:
                continue
            # Embed outside the write lock; only the inserts hold it.
            embeddings = embed_texts([text or "" for _, text in rows])
            conn.execute("BEGIN IMMEDIATE")
            try:
                for (chunk_id, _), emb in zip(rows, embeddings, strict=True):
                    # Another process may have embedded it meanwhile; vec0 has no upsert.
                    if conn.execute("SELECT 1 FROM chunk_vec WHERE chunk_id = ?", (chunk_id,)).fetchone():
                        continue
                    conn.execute(
                        "INSERT INTO chunk_vec (chunk_id, embedding) VALUES (?, ?)",
                        (chunk_id, serialize_embedding(emb)),
                    )
                    result["embedded"] += 1
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            if progress:
                done = min(start + _BATCH, len(missing))
                print(f"\r  Embedding chunks… {done}/{len(missing)}", end="", flush=True)
        if progress:
            print()
        logger.info(
            "Vector sync: embedded %d, removed %d (%.1fs)",
            result["embedded"], result["removed"], time.monotonic() - started,
        )
        return result
    finally:
        conn.close()


# ── Background syncer (one per process) ────────────────────────────────────

class _VectorSyncer:
    def __init__(self, db_path: str, debounce: float, interval: float):
        self.db_path = db_path
        self.debounce = debounce
        self.interval = interval
        self.loop = asyncio.get_running_loop()
        self.wake = asyncio.Event()
        self.wake.set()  # sync once at startup
        self.task = self.loop.create_task(self._run(), name="chunk-vector-sync")

    async def _run(self) -> None:
        timeout = self.interval
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), timeout=timeout)
            await asyncio.sleep(self.debounce)  # coalesce bursts of writes
            self.wake.clear()
            timeout = self.interval
            try:
                await asyncio.to_thread(sync_chunk_vectors, self.db_path)
            except asyncio.CancelledError:
                raise
            except sqlite3.OperationalError as e:
                if not _is_lock_error(e):
                    logger.warning("Vector sync failed; will retry", exc_info=True)
                    continue
                # Expected while another process holds a long write (e.g. `llmwiki reindex`
                # inserting every document in one transaction): retry soon, quietly.
                logger.warning("Vector sync: index busy (%s); retrying in %.0fs", e, _LOCK_RETRY_S)
                timeout = _LOCK_RETRY_S
            except Exception:
                logger.warning("Vector sync failed; will retry", exc_info=True)

    def request(self) -> None:
        try:
            if asyncio.get_running_loop() is self.loop:
                self.wake.set()
                return
        except RuntimeError:
            pass
        self.loop.call_soon_threadsafe(self.wake.set)


_syncer: _VectorSyncer | None = None


def start_vector_sync(db_path: str, *, debounce: float = 2.0, interval: float = 300.0) -> None:
    """Start the background syncer for this process. Call from a running event loop.

    Set ``LLMWIKI_VECTOR_SYNC=0`` to disable it (the test suite does; reindex still
    embeds via ``sync_chunk_vectors``).
    """
    global _syncer
    if os.environ.get("LLMWIKI_VECTOR_SYNC", "1") == "0":
        return
    if _syncer is None:
        _syncer = _VectorSyncer(db_path, debounce, interval)


def request_vector_sync() -> None:
    """Ask the background syncer to reconcile soon. No-op if it isn't running."""
    if _syncer is not None:
        _syncer.request()


async def stop_vector_sync() -> None:
    global _syncer
    if _syncer is None:
        return
    task, _syncer = _syncer.task, None
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
