"""SQLite + sqlite-vec store for the bi-temporal memory layer.

Owns its OWN database file (``{workspace}/.llmwiki/memory.db``) — it never opens
the wiki index (``index.db``) for writing, so the existing llmwiki server cannot
be affected by anything here.

Durability: the database is derived state. The durable record is append-only
JSONL under ``{workspace}/wiki/.memory/`` (episodes / claims / clarifications).
``MemoryStore.init`` rebuilds the database from that JSONL when memory.db is
missing or empty, so ``rm memory.db`` is fully recoverable.

Mirrors the module-global connection pattern of ``mcp/vaultfs/sqlite.py``.
"""

import hashlib
import json
import logging
import sys
import uuid
from pathlib import Path

import aiosqlite
import sqlite_vec

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from embedder import EMBEDDING_DIM

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
_BACKFILL_BATCH = 64

_db: aiosqlite.Connection | None = None
_workspace_root: Path | None = None

# Whitelisted columns for JSONL replay (guards against injection via dict keys).
_EPISODE_COLS = [
    "id", "kind", "summary", "detail", "source_path", "source_document_id",
    "actor", "occurred_at", "recorded_at", "metadata", "content_hash",
]
_CLAIM_COLS = [
    "id", "claim_type", "subject", "statement", "rationale", "confidence",
    "valid_at", "invalid_at", "recorded_at", "expired_at",
    "superseded_by", "supersedes", "episode_id", "source_path",
    "source_document_id", "content_hash", "created_at",
]
_CLARIFICATION_COLS = [
    "id", "origin", "status", "question", "options", "candidate_claim_ids",
    "proposed_action", "confidence", "uncertainty_reasons", "resolution",
    "resolved_by", "resolved_at", "created_at", "content_hash",
]


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(p or "" for p in parts).encode("utf-8")).hexdigest()


def _rows_to_dicts(cursor: aiosqlite.Cursor, rows: list[tuple]) -> list[dict]:
    cols = [d[0] for d in cursor.description]
    out = []
    for row in rows:
        d = dict(zip(cols, row))
        for jf in ("options", "candidate_claim_ids", "uncertainty_reasons", "metadata"):
            if jf in d and isinstance(d[jf], str):
                try:
                    d[jf] = json.loads(d[jf])
                except (json.JSONDecodeError, TypeError):
                    pass
        out.append(d)
    return out


def _rrf_combine_claims(fts: list[dict], vec: list[dict], limit: int, k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion over claim results, keyed on claim id.

    Same 1/(k+rank+1) scoring as the wiki's _rrf_combine, re-keyed for claims.
    """
    scores: dict[str, float] = {}
    result_map: dict[str, dict] = {}
    for rank, r in enumerate(fts):
        key = r["id"]
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
        result_map[key] = r
    for rank, r in enumerate(vec):
        key = r["id"]
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
        result_map.setdefault(key, r)
    ordered = sorted(scores, key=lambda x: scores[x], reverse=True)
    results = []
    for key in ordered[:limit]:
        d = dict(result_map[key])
        d["score"] = scores[key]
        results.append(d)
    return results


def _fts_query(text: str) -> str | None:
    """Turn arbitrary text into a safe FTS5 MATCH query (OR of quoted tokens)."""
    tokens = [t for t in "".join(c if c.isalnum() else " " for c in text).split() if len(t) >= 2]
    if not tokens:
        return None
    return " OR ".join(f'"{t}"' for t in tokens[:32])


class MemoryStore:
    """Bi-temporal claim/episode store. One workspace = one memory.db."""

    def __init__(self, user_id: str = "local"):
        self.user_id = user_id

    # ---------------------------------------------------------------- lifecycle
    @staticmethod
    async def init(workspace_path: str) -> None:
        global _db, _workspace_root
        _workspace_root = Path(workspace_path).resolve()
        (_workspace_root / ".llmwiki").mkdir(parents=True, exist_ok=True)
        _memory_dir().mkdir(parents=True, exist_ok=True)

        db_path = _workspace_root / ".llmwiki" / "memory.db"
        _db = await aiosqlite.connect(str(db_path))
        await _db.enable_load_extension(True)
        await _db.load_extension(sqlite_vec.loadable_path())
        await _db.enable_load_extension(False)
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA busy_timeout=30000")
        await _db.execute("PRAGMA foreign_keys=ON")
        if _SCHEMA_PATH.exists():
            await _db.executescript(_SCHEMA_PATH.read_text())
            await _db.commit()
        await _db.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS claim_vec USING vec0("
            f"claim_id text primary key, embedding float[{EMBEDDING_DIM}])"
        )
        await _db.commit()
        await _load_memory(_db)
        logger.info("Memory store initialized (sqlite-vec): %s", db_path)

    @staticmethod
    async def close() -> None:
        global _db
        if _db:
            await _db.close()
            _db = None

    @staticmethod
    def _db_or_raise() -> aiosqlite.Connection:
        if _db is None:
            raise RuntimeError("Memory store not initialized — call MemoryStore.init() first")
        return _db

    # ---------------------------------------------------------------- episodes
    async def record_episode(
        self, kind: str, summary: str, detail: str | None = None,
        source_path: str | None = None, source_document_id: str | None = None,
        actor: str = "claude", occurred_at: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        db = self._db_or_raise()
        ep_id = str(uuid.uuid4())
        chash = _hash(kind, summary, detail or "", actor, occurred_at or "")
        cols = ["id", "kind", "summary", "detail", "source_path",
                "source_document_id", "actor", "content_hash"]
        vals = [ep_id, kind, summary, detail, source_path,
                source_document_id, actor, chash]
        if occurred_at:
            cols.append("occurred_at"); vals.append(occurred_at)
        if metadata is not None:
            cols.append("metadata"); vals.append(json.dumps(metadata))
        placeholders = ", ".join("?" for _ in cols)
        cursor = await db.execute(
            f"INSERT INTO episodes ({', '.join(cols)}) VALUES ({placeholders}) RETURNING *",
            vals,
        )
        row = _rows_to_dicts(cursor, await cursor.fetchall())[0]
        await db.commit()
        _append_jsonl("episodes.jsonl", {"event": "add", "episode": row})
        return row

    async def get_episodes(
        self, limit: int = 20, source_path: str | None = None, since: str | None = None,
    ) -> list[dict]:
        db = self._db_or_raise()
        sql = "SELECT * FROM episodes"
        clauses, params = [], []
        if source_path:
            clauses.append("source_path = ?"); params.append(source_path)
        if since:
            clauses.append("occurred_at >= ?"); params.append(since)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY occurred_at DESC, recorded_at DESC LIMIT ?"
        params.append(limit)
        cursor = await db.execute(sql, params)
        return _rows_to_dicts(cursor, await cursor.fetchall())

    # ---------------------------------------------------------------- claims
    async def add_claim(
        self, statement: str, rationale: str | None = None, claim_type: str = "fact",
        subject: str | None = None, valid_at: str | None = None, confidence: float = 1.0,
        episode_id: str | None = None, source_path: str | None = None,
        source_document_id: str | None = None,
    ) -> dict:
        db = self._db_or_raise()
        claim_id = str(uuid.uuid4())
        chash = _hash(claim_type, subject or "", statement, rationale or "")
        cols = ["id", "claim_type", "subject", "statement", "rationale", "confidence",
                "episode_id", "source_path", "source_document_id", "content_hash"]
        vals = [claim_id, claim_type, subject, statement, rationale, confidence,
                episode_id, source_path, source_document_id, chash]
        if valid_at:
            cols.append("valid_at"); vals.append(valid_at)
        placeholders = ", ".join("?" for _ in cols)
        cursor = await db.execute(
            f"INSERT INTO claims ({', '.join(cols)}) VALUES ({placeholders}) RETURNING *",
            vals,
        )
        row = _rows_to_dicts(cursor, await cursor.fetchall())[0]
        await db.commit()
        await _embed_claim(db, claim_id, statement, rationale)
        _append_jsonl("claims.jsonl", {"event": "add", "claim": row})
        return row

    async def supersede_claim(
        self, old_id: str, new_id: str, invalid_at: str | None = None,
    ) -> dict | None:
        """Append-only supersession: close the old claim, link both ways. Old row stays queryable."""
        db = self._db_or_raise()
        await db.execute(
            "UPDATE claims SET superseded_by = ?, expired_at = datetime('now'), "
            "invalid_at = COALESCE(?, datetime('now')) "
            "WHERE id = ? AND superseded_by IS NULL",
            (new_id, invalid_at, old_id),
        )
        await db.execute("UPDATE claims SET supersedes = ? WHERE id = ?", (old_id, new_id))
        await db.commit()
        cursor = await db.execute("SELECT * FROM claims WHERE id = ?", (old_id,))
        rows = _rows_to_dicts(cursor, await cursor.fetchall())
        old = rows[0] if rows else None
        _append_jsonl("claims.jsonl", {
            "event": "supersede", "old_id": old_id, "new_id": new_id,
            "invalid_at": old.get("invalid_at") if old else invalid_at,
            "expired_at": old.get("expired_at") if old else None,
        })
        return old

    async def get_claim(self, claim_id: str) -> dict | None:
        db = self._db_or_raise()
        cursor = await db.execute("SELECT * FROM claims WHERE id = ?", (claim_id,))
        rows = _rows_to_dicts(cursor, await cursor.fetchall())
        return rows[0] if rows else None

    async def get_claim_chain(self, claim_id: str) -> list[dict]:
        """Walk supersedes/superseded_by both ways → ordered A→B→C chain (oldest first)."""
        db = self._db_or_raise()
        start = await self.get_claim(claim_id)
        if not start:
            return []
        # walk backwards to the oldest ancestor
        seen = {start["id"]}
        cur = start
        while cur.get("supersedes"):
            prev = await self.get_claim(cur["supersedes"])
            if not prev or prev["id"] in seen:
                break
            seen.add(prev["id"]); cur = prev
        # walk forward collecting the chain
        chain = [cur]
        while cur.get("superseded_by"):
            nxt = await self.get_claim(cur["superseded_by"])
            if not nxt or nxt["id"] in {c["id"] for c in chain}:
                break
            chain.append(nxt); cur = nxt
        return chain

    async def all_current_claims(self, limit: int = 1000) -> list[dict]:
        db = self._db_or_raise()
        cursor = await db.execute("SELECT * FROM current_claims ORDER BY created_at LIMIT ?", (limit,))
        return _rows_to_dicts(cursor, await cursor.fetchall())

    async def claims_by_subject(
        self, subject: str, include_superseded: bool = True, limit: int = 50,
    ) -> list[dict]:
        db = self._db_or_raise()
        sql = "SELECT * FROM claims WHERE subject = ?"
        if not include_superseded:
            sql += " AND expired_at IS NULL AND invalid_at IS NULL"
        sql += " ORDER BY created_at LIMIT ?"
        cursor = await db.execute(sql, (subject, limit))
        return _rows_to_dicts(cursor, await cursor.fetchall())

    async def search_claims(
        self, query: str, limit: int = 8, include_superseded: bool = False,
        claim_type: str | None = None, subject: str | None = None,
        as_of: str | None = None,
    ) -> list[dict]:
        db = self._db_or_raise()
        fetch = limit * 3
        try:
            fts = await self._search_fts(db, query, fetch, include_superseded, claim_type, subject, as_of)
        except Exception:
            logger.debug("claim FTS search failed", exc_info=True)
            fts = []
        try:
            vec = await self._search_vec(db, query, fetch, include_superseded, claim_type, subject, as_of)
        except Exception:
            logger.debug("claim vector search unavailable", exc_info=True)
            vec = []
        if not vec:
            return fts[:limit]
        if not fts:
            return vec[:limit]
        return _rrf_combine_claims(fts, vec, limit)

    def _temporal_filter(self, include_superseded: bool, as_of: str | None) -> tuple[str, list]:
        if as_of:
            return ("c.recorded_at <= ? AND (c.expired_at IS NULL OR c.expired_at > ?)", [as_of, as_of])
        if not include_superseded:
            return ("c.expired_at IS NULL AND c.invalid_at IS NULL", [])
        return ("1=1", [])

    async def _search_fts(self, db, query, limit, include_superseded, claim_type, subject, as_of):
        match = _fts_query(query)
        if not match:
            return []
        where, params = self._temporal_filter(include_superseded, as_of)
        sql = (
            "SELECT c.*, rank as fts_rank FROM claims c "
            "JOIN claim_fts f ON c.rowid = f.rowid "
            f"WHERE claim_fts MATCH ? AND {where} "
        )
        args = [match] + params
        if claim_type:
            sql += "AND c.claim_type = ? "; args.append(claim_type)
        if subject:
            sql += "AND c.subject = ? "; args.append(subject)
        sql += "ORDER BY rank LIMIT ?"; args.append(limit)
        cursor = await db.execute(sql, args)
        return _rows_to_dicts(cursor, await cursor.fetchall())

    async def _search_vec(self, db, query, limit, include_superseded, claim_type, subject, as_of):
        from embedder import embed_query, serialize_embedding
        q = serialize_embedding(embed_query(query))
        where, params = self._temporal_filter(include_superseded, as_of)
        sql = (
            "SELECT c.*, sub.distance as distance FROM "
            "(SELECT claim_id, distance FROM claim_vec WHERE embedding MATCH ? AND k = ?) sub "
            "JOIN claims c ON c.id = sub.claim_id "
            f"WHERE {where} "
        )
        args = [q, limit] + params
        if claim_type:
            sql += "AND c.claim_type = ? "; args.append(claim_type)
        if subject:
            sql += "AND c.subject = ? "; args.append(subject)
        sql += "ORDER BY sub.distance"
        cursor = await db.execute(sql, args)
        return _rows_to_dicts(cursor, await cursor.fetchall())

    async def similar_current_claims(self, statement: str, limit: int = 5, exclude_id: str | None = None) -> list[dict]:
        """Current claims most similar to `statement`, each annotated with cosine `similarity`."""
        results = await self.search_claims(statement, limit=limit + (1 if exclude_id else 0))
        results = [r for r in results if r["id"] != exclude_id]
        if results:
            sims = _cosine_against(statement, [r["statement"] for r in results])
            for r, s in zip(results, sims):
                r["similarity"] = s
        return results[:limit]

    # ---------------------------------------------------------------- clarifications
    async def create_clarification(
        self, origin: str, question: str, options: dict,
        candidate_claim_ids: list[str], proposed_action: str | None = None,
        confidence: float | None = None, uncertainty_reasons: list[str] | None = None,
    ) -> dict:
        db = self._db_or_raise()
        cid = str(uuid.uuid4())
        chash = _hash(origin, question, json.dumps(candidate_claim_ids, sort_keys=True))
        cursor = await db.execute(
            "INSERT INTO clarifications (id, origin, question, options, candidate_claim_ids, "
            "proposed_action, confidence, uncertainty_reasons, content_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING *",
            (cid, origin, question, json.dumps(options), json.dumps(candidate_claim_ids),
             proposed_action, confidence,
             json.dumps(uncertainty_reasons) if uncertainty_reasons is not None else None, chash),
        )
        row = _rows_to_dicts(cursor, await cursor.fetchall())[0]
        await db.commit()
        _append_jsonl("clarifications.jsonl", {"event": "create", "clarification": row})
        return row

    async def list_clarifications(self, status: str = "open") -> list[dict]:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT * FROM clarifications WHERE status = ? ORDER BY created_at DESC", (status,)
        )
        return _rows_to_dicts(cursor, await cursor.fetchall())

    async def resolve_clarification(self, clar_id: str, choice: str, resolved_by: str = "user") -> dict | None:
        db = self._db_or_raise()
        cursor = await db.execute("SELECT * FROM clarifications WHERE id = ?", (clar_id,))
        rows = _rows_to_dicts(cursor, await cursor.fetchall())
        if not rows:
            return None
        clar = rows[0]
        opts = clar["options"].get("options", []) if isinstance(clar["options"], dict) else []
        chosen = _match_option(opts, choice)
        if chosen is None:
            return None
        await self._apply_action(chosen.get("action") or {})
        await db.execute(
            "UPDATE clarifications SET status = 'resolved', resolution = ?, "
            "resolved_by = ?, resolved_at = datetime('now') WHERE id = ?",
            (chosen.get("label", choice), resolved_by, clar_id),
        )
        await db.commit()
        _append_jsonl("clarifications.jsonl", {
            "event": "resolve", "id": clar_id, "resolution": chosen.get("label", choice),
            "resolved_by": resolved_by,
        })
        return await self._get_clarification(clar_id)

    async def _get_clarification(self, clar_id: str) -> dict | None:
        db = self._db_or_raise()
        cursor = await db.execute("SELECT * FROM clarifications WHERE id = ?", (clar_id,))
        rows = _rows_to_dicts(cursor, await cursor.fetchall())
        return rows[0] if rows else None

    async def _apply_action(self, action: dict) -> None:
        atype = action.get("type")
        if atype in ("supersede", "merge"):
            old_id, new_id = action.get("old_id"), action.get("new_id")
            if old_id and new_id:
                await self.supersede_claim(old_id, new_id)
        # keep_both / noop → nothing to mutate (both claims remain current)


# ---------------------------------------------------------------- helpers (module level)
def _memory_dir() -> Path:
    assert _workspace_root is not None
    return _workspace_root / "wiki" / ".memory"


def _append_jsonl(filename: str, obj: dict) -> None:
    if _workspace_root is None:
        return
    path = _memory_dir() / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _cosine_against(text: str, others: list[str]) -> list[float]:
    """Cosine similarity of `text` vs each of `others` (embeddings are L2-normalized → dot product)."""
    try:
        from embedder import embed_texts
    except Exception:
        return [0.0] * len(others)
    if not others:
        return []
    embs = embed_texts([text] + others)
    base = embs[0]
    return [sum(a * b for a, b in zip(base, e)) for e in embs[1:]]


async def _embed_claim(db, claim_id: str, statement: str, rationale: str | None) -> None:
    try:
        from embedder import embed_texts, serialize_embedding
    except Exception:
        logger.warning("Cannot embed claim — embedding model unavailable")
        return
    text = statement + (" " + rationale if rationale else "")
    emb = embed_texts([text])[0]
    await db.execute(
        "INSERT OR REPLACE INTO claim_vec (claim_id, embedding) VALUES (?, ?)",
        (claim_id, serialize_embedding(emb)),
    )
    await db.commit()


def _match_option(options: list[dict], choice: str) -> dict | None:
    if not options:
        return None
    # by index
    if choice.isdigit():
        idx = int(choice)
        if 0 <= idx < len(options):
            return options[idx]
    # by exact label (case-insensitive)
    for o in options:
        if (o.get("label") or "").lower() == choice.lower():
            return o
    return None


def _insert_row(db, table: str, cols: list[str], row: dict):
    present = [c for c in cols if c in row and row[c] is not None]
    if "id" not in present:
        return None
    placeholders = ", ".join("?" for _ in present)
    vals = [json.dumps(row[c]) if isinstance(row[c], (dict, list)) else row[c] for c in present]
    return db.execute(
        f"INSERT OR IGNORE INTO {table} ({', '.join(present)}) VALUES ({placeholders})", vals
    )


async def _load_memory(db: aiosqlite.Connection) -> None:
    """Rebuild memory.db from append-only JSONL when the DB is empty; always backfill vectors."""
    cursor = await db.execute("SELECT count(*) FROM claims")
    have_claims = (await cursor.fetchone())[0]
    cursor = await db.execute("SELECT count(*) FROM episodes")
    have_eps = (await cursor.fetchone())[0]

    if have_claims == 0 and have_eps == 0:
        await _replay_jsonl(db)

    await _backfill_claim_embeddings(db)


async def _replay_jsonl(db: aiosqlite.Connection) -> None:
    mem = _memory_dir()
    # episodes first (claims FK episode_id)
    ep_file = mem / "episodes.jsonl"
    if ep_file.exists():
        for obj in _read_jsonl(ep_file):
            if obj.get("event") == "add" and obj.get("episode"):
                stmt = _insert_row(db, "episodes", _EPISODE_COLS, obj["episode"])
                if stmt is not None:
                    await stmt
    # claims: add then supersede, in file order
    cl_file = mem / "claims.jsonl"
    if cl_file.exists():
        for obj in _read_jsonl(cl_file):
            ev = obj.get("event")
            if ev == "add" and obj.get("claim"):
                stmt = _insert_row(db, "claims", _CLAIM_COLS, obj["claim"])
                if stmt is not None:
                    await stmt
            elif ev == "supersede":
                await db.execute(
                    "UPDATE claims SET superseded_by = ?, expired_at = COALESCE(?, datetime('now')), "
                    "invalid_at = COALESCE(?, datetime('now')) WHERE id = ?",
                    (obj["new_id"], obj.get("expired_at"), obj.get("invalid_at"), obj["old_id"]),
                )
                await db.execute(
                    "UPDATE claims SET supersedes = ? WHERE id = ?", (obj["old_id"], obj["new_id"])
                )
    # clarifications: create then resolve
    clar_file = mem / "clarifications.jsonl"
    if clar_file.exists():
        for obj in _read_jsonl(clar_file):
            ev = obj.get("event")
            if ev == "create" and obj.get("clarification"):
                stmt = _insert_row(db, "clarifications", _CLARIFICATION_COLS, obj["clarification"])
                if stmt is not None:
                    await stmt
            elif ev == "resolve":
                await db.execute(
                    "UPDATE clarifications SET status = 'resolved', resolution = ?, "
                    "resolved_by = ?, resolved_at = datetime('now') WHERE id = ?",
                    (obj.get("resolution"), obj.get("resolved_by", "user"), obj["id"]),
                )
    await db.commit()
    logger.info("Replayed memory from JSONL")


def _read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSONL line in %s", path.name)


async def _backfill_claim_embeddings(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("SELECT count(*) FROM claims")
    total = (await cursor.fetchone())[0]
    if total == 0:
        return
    cursor = await db.execute("SELECT count(*) FROM claim_vec")
    embedded = (await cursor.fetchone())[0]
    if embedded >= total:
        return
    try:
        from embedder import embed_texts, serialize_embedding
    except Exception:
        logger.warning("Cannot backfill claim embeddings — model unavailable")
        return
    cursor = await db.execute(
        "SELECT id, statement, rationale FROM claims WHERE id NOT IN (SELECT claim_id FROM claim_vec)"
    )
    rows = await cursor.fetchall()
    for i in range(0, len(rows), _BACKFILL_BATCH):
        batch = rows[i:i + _BACKFILL_BATCH]
        texts = [s + (" " + r if r else "") for _, s, r in batch]
        embs = embed_texts(texts)
        await db.executemany(
            "INSERT OR IGNORE INTO claim_vec (claim_id, embedding) VALUES (?, ?)",
            [(rid, serialize_embedding(e)) for (rid, _, _), e in zip(batch, embs)],
        )
    await db.commit()
    logger.info("Backfilled %d claim embeddings", len(rows))
