# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A fork of [lucasastorian/llmwiki](https://github.com/lucasastorian/llmwiki) (git remote `upstream`, tracks its `master`) that adds **hybrid semantic search** to the local SQLite backend via [sqlite-vec](https://github.com/asg017/sqlite-vec). The upstream local mode was FTS5 keyword-only; this fork adds 384-dim embeddings (`all-MiniLM-L6-v2`) and fuses keyword + vector results with Reciprocal Rank Fusion. See `README.md` for the user-facing story.

## The one architectural fact that explains everything: dual mode

A single codebase runs in two modes, switched by the `MODE` env var (`local` | `hosted`):

| | **local** (this fork's focus) | **hosted** (upstream multi-tenant) |
|---|---|---|
| Storage | SQLite `.llmwiki/index.db` + filesystem | Postgres + S3 |
| Auth | single synthetic user (`uuid5(NAMESPACE_DNS, "local")`) | Supabase JWT |
| Search vectors | sqlite-vec `chunk_vec` (vec0) | Voyage AI + Turbopuffer |
| Embeddings | `shared/embedder.py` (local, CPU) | external API |

Mode is selected once at startup and branches via two patterns you'll see everywhere:
- **API** (`api/main.py` lifespan): builds `LocalServiceFactory` or `HostedServiceFactory` (`api/services/local.py` / `hosted.py`), stored on `app.state.factory`.
- **MCP** (`mcp/`): the `VaultFS` abstraction (`mcp/vaultfs/base.py`) with `SqliteVaultFS` and `PostgresVaultFS` implementations.

When editing a feature, check whether it needs to work in **both** modes — the local and hosted code paths are separate implementations of the same interface, not shared code.

## Source of truth: the filesystem, not the database

In local mode the workspace folder is canonical. `.llmwiki/index.db` is **derived state** — deletable and rebuildable from the files (`llmwiki reindex`). A background file watcher (`api/domain/watcher.py`, started in the API lifespan) picks up edits made outside the app. Never treat the SQLite index as the system of record.

The workspace layout:
- `wiki/` — markdown pages Claude writes/edits via MCP. Plain files.
- `.llmwiki/index.db`, `.llmwiki/cache/` — index + processed artifacts (gitignored, rebuildable).

## Components

| Dir | What it is | Runtime |
|---|---|---|
| `api/` | FastAPI backend | `uvicorn main:app` on :8000, **cwd must be `api/`** |
| `web/` | Next.js 16 / React 19 frontend (Tailwind, tiptap editor) | `npm run dev` on :3000, cwd `web/` |
| `mcp/` | stdio MCP server Claude connects to (wiki tools) | `python -m local_server`, **cwd must be `mcp/`** |
| `memory/` | **standalone** bi-temporal memory MCP server (see below) | `python -m memory.server`, cwd repo root |
| `shared/` | `sqlite_migrations/` (canonical local schema), `embedder.py` (local embedding model), `chunk_vectors.py` (fork: keeps `chunk_vec` in sync) | imported by all of the above |
| `converter/` | optional LibreOffice office-doc → PDF microservice | separate FastAPI app |
| `supabase/` | Postgres migrations for hosted mode | — |

**cwd / imports matter.** `api/`, `mcp/`, and `memory/` each use top-level absolute imports (`from config import ...`, `from tools import ...`) that only resolve when run from their own directory — that's why `run-mcp.sh` does `cd "$DIR/mcp"` and the CLI launches uvicorn with `cwd=api/`. Each module also does `sys.path.insert(..., "shared")` to import `embedder`.

## Hybrid search (the fork's core change)

Implemented in `mcp/vaultfs/sqlite.py::search_chunks`. Both signals run on every query, then merge:
- **FTS5 BM25** (`chunks_fts`, porter stemming; upstream quotes every term, so all terms must match) — `_select_chunk_matches`
- **sqlite-vec cosine** (`chunk_vec` vec0 table, 384-dim) — `_select_vector_matches`
- Merged by `_rrf_combine` (Reciprocal Rank Fusion, k=60, equal weight; fused score shown as 0–100).

Upstream's `scope` / `annotated_only` filters still apply: `scope="annotations"` is keyword-only (vectors embed source text, not annotations); in `scope="source"` a vector hit counts as a source match.

Graceful degradation is intentional and load-bearing: if either signal fails (no embeddings yet, model unavailable) search falls back to whatever works. Keep this property when modifying search.

**Embeddings are reconciled, not written inline.** Upstream writes chunks from many places (ingest, watcher, MCP create/edit/append, highlight rewrites) and replaces them wholesale on every edit. `shared/chunk_vectors.py::sync_chunk_vectors` makes `chunk_vec` mirror `document_chunks` — drops vectors whose chunk is gone (vec0 has no FK cascade), embeds chunks with no vector (from `source_content`, the immutable raw text; `content` also carries highlight annotations). It is idempotent and multi-process safe (inserts under `BEGIN IMMEDIATE` with a presence check).
- **Background**: `start_vector_sync` runs it in the API lifespan and in `SqliteVaultFS.init` (MCP) — at startup, ~2s after `request_vector_sync()` (called from every chunk write: `local_processor._store_chunks`, `SQLiteChunkRepository.store`, `mcp/vaultfs/chunker.store_chunks_sqlite`), and every 5 min as a safety net.
- **Reindex**: `api/reindex_finish.py` runs it synchronously with progress.

If you add a new chunk-write path, call `request_vector_sync()` after it (or rely on the 5-min sweep). Embeddings are L2-normalized so cosine == dot product. `chunk_vec` is created in code (`VEC_TABLE_DDL`), not in a migration — the migration runner uses plain `sqlite3` without the extension. Any connection that *reads* `chunk_vec` must load sqlite-vec first (`load_sqlite_vec_async`).

## Citation graph (fork fixes)

Footnote targets are parsed in **two** places with separate import roots — `mcp/tools/references.py` (MCP writes, `lint`) and `api/services/references.py` (API `POST …/graph/rebuild`, reindex). Keep them in sync. Fork fixes vs upstream: filename anchored on a known extension (date-prefixed `2026-06-23 - A - B.md` isn't cut at the first ` - `), and `[ \t]*` instead of `\s*` after `]:` so an inline `**claim**[^x]:` doesn't read the next line.

## Schema

Canonical local schema: numbered migrations in `shared/sqlite_migrations/` (`0001_baseline.sql`, …), applied by `api/infra/db/local_migrations.py` (stdlib-only; loaded by path from the API, MCP and CLI; tracks `PRAGMA user_version`; reconciles pre-versioning DBs by adding missing columns). To change the schema, add a new numbered file — never edit an applied one.

## Memory server (isolated, optional)

`memory/` is a second MCP server adding a bi-temporal, continuously-learning layer. It is deliberately **non-breaking**: own database (`.llmwiki/memory.db`), own append-only durable log (`wiki/.memory/*.jsonl`, from which the db is rebuilt on startup), own schema (`memory/schema.sql`). It never touches `index.db` or the wiki server.

Core idea: facts/decisions are **superseded, not deleted** (append-only bi-temporal claims with valid-time + transaction-time). An uncertainty gate (`AUTO_APPLY_THRESHOLD`) auto-applies confident merges and escalates ambiguous ones as AskUserQuestion-shaped *clarifications*. Optional background consolidation uses a local LLM via Ollama. Full details in `memory/README.md`.

## Common commands

```bash
# One-time setup (single venv for api + mcp + memory)
python3 -m venv .venv && source .venv/bin/activate
pip install -r api/requirements.txt -r mcp/requirements.txt
cd web && npm install && cd ..

# Run the local app (init if needed + API + web + open browser)
./llmwiki open ~/research          # or: init / serve / reindex / mcp / mcp-config

# Run the MCP servers (what Claude connects to)
./run-mcp.sh ~/research            # wiki MCP server
./run-memory-mcp.sh ~/research     # memory MCP server (parallel, same workspace)
```

CLI verbs (`./llmwiki <verb> <workspace>`): `open` (init+serve+browser), `init`, `serve`, `mcp` (stdio), `mcp-config` (prints Claude config snippet), `reindex` (rebuild index.db from disk).

`reindex` backs up `index.db` to `index.db.bak-<timestamp>`, asks for confirmation (pass `--yes` when non-interactive) because it **discards index-only state** (highlights, comments, replies, quiz progress, clip metadata), then — fork addition — runs `api/reindex_finish.py` to chunk, rebuild the reference graph, and embed. A healthy run prints `✓ Chunked …`, `✓ Reference graph rebuilt …` and `✓ Embeddings in sync …`; a `⚠` line means one of those didn't happen. Run it with `serve` stopped.

MCP tools (upstream): `guide`, `list_knowledge_bases`, `create_knowledge_base`, `update_knowledge_base`, `search`, `read`, `create`, `edit` (exact string replace), `append`, `delete`, `lint`, `list_comments`, `reply_to_comment`, `add_source_from_url`. There is no `write` tool any more.

## Syncing with upstream

```bash
git fetch upstream && git merge upstream/master   # on a branch; then re-run tests
```
Fork-owned code is kept in separate files where possible (`shared/chunk_vectors.py`, `api/reindex_finish.py`, `api/services/stats.py`, `api/routes/local_stats.py`, `memory/`) with small marked hooks (`# Fork:`) in upstream files, so merges stay mechanical. Expect conflicts mainly in `mcp/vaultfs/sqlite.py::search_chunks`, the two `references.py` parsers, `llmwiki`, `README.md` and the requirements files (the hash-locked `*.lock` files don't include the fork's deps — they're only used by the Docker images).

## Tests

Most integration tests run against **hosted mode** (asyncpg) and need a test Postgres:

```bash
docker compose -f docker-compose.test.yml up -d        # Postgres 16 on :5434
pip install -r tests/requirements.txt
pytest                                                  # from repo root (pytest.ini: asyncio auto)
pytest tests/integration/isolation/                     # RLS / tenant-isolation suite
pytest tests/integration/test_kb_lifecycle.py::test_name # single test

# Memory server tests (uses an injected fake LLM — no Ollama/Postgres needed)
python -m pytest tests/integration/memory/
```

`tests/conftest.py` hardcodes `MODE=hosted` and `DATABASE_URL=...localhost:5434/supavault_test`, and adds `api/` to `sys.path`. The isolation suite (`tests/integration/isolation/`, `mcp/`) exists to verify multi-tenant data separation in hosted mode — keep these green when touching auth, scoped queries, or the `VaultFS`/factory interfaces.

## Conventions worth knowing

- **Everything local-first by default.** No API keys required for the local path. `MISTRAL_API_KEY` only upgrades PDF OCR quality; `PDF_BACKEND` config picks the extractor.
- **Settings** are centralized in `api/config.py` (`pydantic-settings`, reads `../.env`). Many fields are hosted-only.
- **One workspace = one MCP server entry.** Multiple research folders mean multiple server registrations — this scoping is intentional.
