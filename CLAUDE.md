# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A fork of [lucasastorian/llmwiki](https://github.com/lucasastorian/llmwiki) that adds **hybrid semantic search** to the local SQLite backend via [sqlite-vec](https://github.com/asg017/sqlite-vec). The upstream local mode was FTS5 keyword-only; this fork adds 384-dim embeddings (`all-MiniLM-L6-v2`) and fuses keyword + vector results with Reciprocal Rank Fusion. See `README.md` for the user-facing story.

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
| `shared/` | `embedder.py` (the local embedding model) + `sqlite_schema.sql` (canonical local schema) | imported by all of the above |
| `converter/` | optional LibreOffice office-doc → PDF microservice | separate FastAPI app |
| `supabase/` | Postgres migrations for hosted mode | — |

**cwd / imports matter.** `api/`, `mcp/`, and `memory/` each use top-level absolute imports (`from config import ...`, `from tools import ...`) that only resolve when run from their own directory — that's why `run-mcp.sh` does `cd "$DIR/mcp"` and the CLI launches uvicorn with `cwd=api/`. Each module also does `sys.path.insert(..., "shared")` to import `embedder`.

## Hybrid search (the fork's core change)

Implemented in `mcp/vaultfs/sqlite.py::search_chunks`. Both signals run on every query, then merge:
- **FTS5 BM25** (`chunks_fts`, porter stemming) — `_search_fts`
- **sqlite-vec cosine** (`chunk_vec` vec0 table, 384-dim) — `_search_vec`
- Merged by `_rrf_combine` (Reciprocal Rank Fusion, k=60, equal weight).

Graceful degradation is intentional and load-bearing: if either signal fails (no embeddings yet, malformed FTS query, model unavailable) search falls back to whatever works. Keep this property when modifying search.

**Embedding write paths** (all insert into `chunk_vec` from `shared/embedder.py`):
1. Ingest, local API — `api/domain/local_processor.py` + `api/infra/db/sqlite.py`
2. Backfill on MCP startup — `mcp/vaultfs/sqlite.py::_backfill_embeddings` (embeds any chunk missing a vector; this is the one-time cost on first launch)

Embeddings are L2-normalized so cosine == dot product. `chunk_vec` is created as a `vec0` virtual table at init, not in the `.sql` schema file.

## Schema

Canonical local schema: `shared/sqlite_schema.sql` (workspace / documents / document_pages / document_chunks / document_references + `chunks_fts` FTS5 with sync triggers). Loaded by the API lifespan and `SqliteVaultFS.init()`.

⚠️ Gotcha: the standalone `llmwiki init` command references a non-existent `api/infra/db/sqlite_schema.sql` and will fail. Use `llmwiki open` / `serve` / `mcp` instead — they auto-initialize the workspace via the server lifespan, which uses the correct `shared/` schema.

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
