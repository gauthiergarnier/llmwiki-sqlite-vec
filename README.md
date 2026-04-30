# LLM Wiki + sqlite-vec

[![License](https://img.shields.io/badge/license-Apache%202.0-green)](https://opensource.org/licenses/Apache-2.0)

Fork of [lucasastorian/llmwiki](https://github.com/lucasastorian/llmwiki) that adds **hybrid semantic search** to the local SQLite backend using [sqlite-vec](https://github.com/asg017/sqlite-vec).

The original LLM Wiki uses SQLite FTS5 (porter stemming) for keyword-only search in local mode. This fork adds vector embeddings via `all-MiniLM-L6-v2` and combines both signals using Reciprocal Rank Fusion (RRF), so search finds results by meaning — not just matching keywords.

Point it at a folder, start the local app, and connect Claude over MCP. From there, Claude reads your sources, writes wiki pages, and keeps links and citations in sync.

![LLM Wiki — a compiled wiki page with citations and table of contents](wiki-page.png)

## What actually happens

1. **You have a folder** — PDFs, notes, articles, spreadsheets. Your existing research.
2. **LLM Wiki indexes it** — extracts text, chunks for search, builds a local SQLite index. Source files stay where they are.
3. **Claude connects via MCP** — reads sources, writes wiki pages under `wiki/`, maintains cross-references and footnote citations.
4. **The wiki improves** as Claude reads more of the workspace and writes more pages. Summaries, entity pages, and cross-references accumulate instead of being re-derived from scratch each conversation.

## Quick Start

**Requirements:** Python 3.11–3.13, Node.js 20+

```bash
git clone https://github.com/gauthiergarnier/llmwiki-sqlite-vec.git
cd llmwiki-sqlite-vec

# Install Python deps (single venv for both api and mcp)
python3 -m venv .venv && source .venv/bin/activate
pip install -r api/requirements.txt -r mcp/requirements.txt

# Install web deps
cd web && npm install && cd ..

# Initialize a workspace (point at any folder with your files)
./llmwiki init ~/research

# Start the app
./llmwiki serve ~/research
```

On first startup, the embedding model (`all-MiniLM-L6-v2`, ~80MB) is downloaded automatically, and any existing chunks are backfilled with embeddings. This is a one-time cost.

Open [localhost:3000](http://localhost:3000). Your files are indexed, wiki is scaffolded, ready to go.

### Connect Claude

```bash
./llmwiki mcp-config ~/research
```

This prints a JSON snippet for `claude_desktop_config.json` (Claude Desktop) or `.claude/settings.json` (Claude Code). One workspace runs as one MCP server entry, so if you have multiple research folders, add one entry per folder.

Then tell Claude: *"Read the guide, then ingest my sources and start building the wiki."*

### One-command start

```bash
./llmwiki open ~/research
```

Does everything: init if needed, start servers, open browser, print MCP config hint.

## CLI

| Command | What it does |
|---------|-------------|
| `llmwiki open <folder>` | Init + serve + open browser |
| `llmwiki init <folder>` | Create `.llmwiki/` + `wiki/`, index existing files |
| `llmwiki serve <folder>` | Start API on :8000 + web on :3000 |
| `llmwiki mcp <folder>` | Run stdio MCP server (for Claude config) |
| `llmwiki mcp-config <folder>` | Print `claude_desktop_config.json` snippet |
| `llmwiki reindex <folder>` | Rebuild the index from disk |

## What happens on disk

LLM Wiki adds two things to your folder. Source files are not moved or modified.

```
~/research/                  # Your existing files (untouched)
  papers/paper.pdf
  notes.md
  data.xlsx
  wiki/                      # Generated pages (created by LLM Wiki)
    overview.md
    log.md
    concepts/
      attention.md
  .llmwiki/                  # Index + cache (hidden, rebuildable)
    index.db
    cache/
```

- `wiki/` — ordinary markdown files. Edit them in any editor. Claude writes and updates them via MCP.
- `.llmwiki/` — SQLite search index and processed artifacts. Delete it anytime; `llmwiki reindex` rebuilds from the source files.

By default, indexing, storage, and file writes happen on your machine. No cloud services required.

## How Claude interacts with the workspace

Once connected, Claude has these tools:

| Tool | Description |
|------|-------------|
| `guide` | Explains how the wiki works, lists what's in the workspace |
| `search` | Browse files (`list`) or full-text search (`search`) |
| `read` | Read documents — PDFs with page ranges, glob batch reads |
| `write` | Create wiki pages, edit with `str_replace`, append. SVG/CSV assets |
| `delete` | Delete documents by path or glob pattern |

All writes go to disk first, then update the search index. If Claude creates `/wiki/concepts/attention.md`, that file appears on disk immediately.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────────────┐
│   Next.js    │────▶│   FastAPI    │────▶│   SQLite                 │
│   Frontend   │     │   Backend    │     │   ├─ FTS5 (keywords)     │
└──────────────┘     └──────┬───────┘     │   └─ vec0 (embeddings)   │
                            │             └──────────────────────────┘
                     ┌──────┴───────┐
                     │  MCP Server  │◀──── Claude Desktop / Code
                     │   (stdio)    │
                     └──────────────┘
                            │
                     ┌──────┴───────┐
                     │  Filesystem  │  ← source of truth
                     └──────────────┘
```

The filesystem is the source of truth. SQLite is a derived index — it accelerates search and stores extracted page data, but it can always be rebuilt from the files. A background file watcher picks up changes you make outside the app.

## Hybrid search

Search combines two signals via **Reciprocal Rank Fusion** (RRF, k=60):

| Signal | How it works | Good at |
|--------|-------------|---------|
| **FTS5 BM25** | Porter-stemmed keyword matching | Exact terms, names, acronyms |
| **sqlite-vec cosine** | 384-dim embeddings from `all-MiniLM-L6-v2` | Synonyms, paraphrases, conceptual queries |

Both run on every search query. Results are ranked by fused score so that a chunk appearing in both result sets ranks highest. If either signal is unavailable (e.g., no embeddings yet, or a malformed FTS query), search falls back gracefully to whichever signal works.

Embeddings are generated locally at ingest time — no API keys or external services needed.

## Document processing

All processing runs locally. No API keys required for basic usage.

| Format | Parser | Notes |
|--------|--------|-------|
| PDF | pdf-oxide | Rust-based text extraction. Works well for text-heavy papers. Scanned PDFs still benefit from real OCR. |
| Markdown/Text | native | Indexed and chunked directly |
| HTML | webmd | Strips nav/ads, extracts clean markdown |
| Excel/CSV | openpyxl | Sheet-by-sheet extraction |
| Images | native | Stored as-is, viewable inline |
| Word/PowerPoint | LibreOffice | Optional. Install LibreOffice for office conversion; without it, these formats are stored but not extracted. |

Set `MISTRAL_API_KEY` for higher-quality PDF OCR with better table and layout detection. pdf-oxide is the free default and handles most text-heavy documents well enough.

## Limitations and tradeoffs

- **One workspace = one MCP server.** If you work across multiple research projects, each gets its own folder and its own MCP entry. This is intentional — it keeps context and file access scoped.
- **PDF table extraction is rough.** pdf-oxide extracts prose reliably but tables come through as messy text. For financial filings or data-heavy PDFs, Mistral OCR is significantly better.
- **LibreOffice adds setup friction.** Office file conversion requires a local LibreOffice install. If you mostly work with PDFs and markdown, you can skip it entirely.
- **Embedding model adds ~80MB to disk.** The `all-MiniLM-L6-v2` model is downloaded on first use. Embedding generation runs on CPU and adds a few seconds to document ingestion.

## Self-hosting the multi-tenant version

If you want to run the hosted version (like [llmwiki.app](https://llmwiki.app)) with Postgres, Supabase auth, and S3:

<details>
<summary>Hosted setup instructions</summary>

### Prerequisites

- Python 3.11+
- Node.js 20+
- A [Supabase](https://supabase.com) project
- An S3-compatible bucket

### Database

```bash
psql $DATABASE_URL -f supabase/migrations/001_initial.sql
```

### API

```bash
cd api
pip install -r requirements.txt
MODE=hosted DATABASE_URL=postgresql://... uvicorn main:app --port 8000
```

### MCP Server

```bash
cd mcp
pip install -r requirements.txt
MODE=hosted DATABASE_URL=postgresql://... uvicorn server:app --port 8080
```

### Web

```bash
cd web
npm install
NEXT_PUBLIC_MODE=hosted \
NEXT_PUBLIC_SUPABASE_URL=https://your-ref.supabase.co \
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key \
NEXT_PUBLIC_API_URL=http://localhost:8000 \
npm run dev
```

### Environment Variables

**API**
```
MODE=hosted
DATABASE_URL=postgresql://...
SUPABASE_URL=https://your-ref.supabase.co
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
S3_BUCKET=your-bucket
MISTRAL_API_KEY=              # optional, for better PDF OCR
CONVERTER_URL=                # optional, for office conversion
```

**Web**
```
NEXT_PUBLIC_MODE=hosted
NEXT_PUBLIC_SUPABASE_URL=https://your-ref.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
NEXT_PUBLIC_API_URL=http://localhost:8000
```

</details>

## Why this beats a static notes folder

Personal wikis usually fail on maintenance, not intent. Someone has to update links, fix stale summaries, merge overlapping pages, and keep citations aligned with the source material. That work scales with the number of sources, and people stop doing it.

LLM Wiki offloads that editing work. You choose the source material and direct the analysis. Claude handles the repetitive bookkeeping — updating cross-references, keeping summaries current, flagging contradictions, touching the 15 pages that a single new source affects.

## License

Apache 2.0
