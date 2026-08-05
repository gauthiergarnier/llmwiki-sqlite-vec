# Memory — bi-temporal, continuously-learning layer

A **standalone MCP server** that runs alongside the LLM Wiki server against the same
workspace, adding a memory that *learns over time*: it supersedes facts and decisions
while retaining the old ones and the reasoning behind them.

It is deliberately **isolated** from the wiki server:

- Its own database: `{workspace}/.llmwiki/memory.db` (never opens `index.db` for writing).
- Its own durable record: append-only JSONL under `{workspace}/wiki/.memory/`
  (`episodes.jsonl`, `claims.jsonl`, `clarifications.jsonl`). `memory.db` is rebuilt from
  this on startup, so deleting it is fully recoverable.
- Zero changes to `mcp/`, `api/`, or the wiki schema.

## Concepts

- **Claim** — an atomic fact OR decision (also `preference`, `observation`), with a
  **bi-temporal** validity model: *valid time* (`valid_at`/`invalid_at` — true in the
  world) and *transaction time* (`recorded_at`/`expired_at` — when the system learned /
  retired it). Updates are **append-only**: a supersession closes the old claim and links
  it to its replacement; nothing is overwritten or deleted.
- **Episode** — an append-only record of an event (ingest / query / decision / revision /
  lint / consolidation). The queryable, semantic replacement for `wiki/log.md`.
- **Clarification** — an uncertain auto-decision escalated to the user, shaped exactly like
  an AskUserQuestion (a question + options).

## Tools

| Tool | Purpose |
|------|---------|
| `guide` | How the memory works (call first). |
| `recall` | **Quick memory** — current valid facts/decisions only. |
| `history` | **Why we ended there** — supersession chains, subject evolution, `as_of` time-travel. |
| `remember` | Record a fact/decision. `supersedes=<id>` to retire an old one (kept in history). |
| `log_event` | Record an episode without a claim. |
| `clarifications` | List / resolve conflicts the system was unsure about. |
| `ping` | Connectivity check. |

## Run

```bash
# Alongside the wiki server, same workspace:
./run-memory-mcp.sh ~/research
# (equivalent to: python -m memory.server ~/research from the repo root)
```

Register both servers with Claude — see the root `README.md` "Memory" section for the
`.mcp.json` snippet.

## The uncertainty gate (human-in-the-loop)

Every automatic supersede/merge decision — at **ingestion** (`remember` without an explicit
`supersedes`) and in **background consolidation** — carries a `confidence`:

- `confidence >= AUTO_APPLY_THRESHOLD` → applied automatically (append-only).
- below the threshold → **not applied**; a clarification is raised and the conflicting
  claims are left untouched until you resolve it. The fuzzier the call, the more it defers.

Without a local LLM, ingestion uses an embedding-similarity heuristic that flags
near-duplicates for clarification (so it never auto-supersedes on a guess).

## Background consolidation (optional, local LLM via Ollama)

A "sleep-time" job that distills episodes and sweeps current claims for contradictions
when you're idle. Off the hot path; **off by default**.

```bash
# 1. Install Ollama and pull a model (fits a MacBook M5 / 24GB):
ollama pull qwen2.5:7b-instruct      # ~5GB Q4; llama3.1:8b also works; qwen2.5:14b-instruct for higher quality

# 2. Run a consolidation pass:
python -m memory.consolidate ~/research
```

Configuration (env vars or repo-root `.env`; see `memory/config.py`):

| Setting | Default | Meaning |
|---------|---------|---------|
| `CONSOLIDATION_ENABLED` | `false` | Gate for scheduled/automatic runs. |
| `CONSOLIDATION_MODE` | `auto` | `auto` = apply confident decisions + escalate uncertain ones; `review` = escalate everything. |
| `AUTO_APPLY_THRESHOLD` | `0.85` | Confidence needed to auto-apply. |
| `DUPLICATE_SIMILARITY_FLOOR` | `0.88` | No-LLM heuristic floor for flagging a near-duplicate at ingestion. |
| `CONSOLIDATION_CONSIDER_FLOOR` | `0.5` | Min similarity for a pair to be examined during a sweep. |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint. |
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct` | Model used for reasoning. |

If Ollama is unreachable, consolidation logs and exits without changing anything.

### Scheduling (macOS launchd)

A template plist is provided at `memory/com.llmwiki.memory-consolidate.plist.template`.
Copy it, replace `__REPO__` and `__WORKSPACE__` with absolute paths, then:

```bash
cp memory/com.llmwiki.memory-consolidate.plist.template ~/Library/LaunchAgents/com.llmwiki.memory-consolidate.plist
# edit the two placeholders, then:
launchctl load ~/Library/LaunchAgents/com.llmwiki.memory-consolidate.plist
```

## Tests

```bash
python -m pytest tests/integration/memory/
```

Covers bi-temporal supersession, current-vs-history retrieval, `as_of` time-travel, the
rebuild-from-JSONL recovery, the ingestion clarification flow, and the consolidation
sweep (auto + review) with an injected fake LLM (no Ollama needed).
