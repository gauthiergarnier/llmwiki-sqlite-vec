# Search Accuracy Improvement Plan

## Problem

Search ranking in LLM Wiki is purely relevance-based. The `_rrf_combine()` function (`mcp/vaultfs/sqlite.py:45`) merges FTS5 BM25 and vector cosine distance scores using Reciprocal Rank Fusion with equal weights and a fixed k=60. It has no awareness of:

- **Recency**: A 2-year-old brainstorming transcript ranks identically to yesterday's final decision document.
- **Document type authority**: Wiki pages (curated summaries) rank the same as raw meeting notes or email threads.
- **Metadata in embeddings**: Chunks are embedded as raw text with no context about their source document type, date, or title.

The `documents` table already stores `source_kind`, `date`, `created_at`, `updated_at`, and `metadata` — but none of these are fetched or used by the search queries.

---

## Phase 1 — RRF Scoring Enhancements

**Goal**: Add recency decay and source-kind boost as post-RRF multipliers. No schema changes needed.

**Estimated effort**: 1–2 days

### 1.1 Fetch metadata in search queries

Both `_search_fts()` (line 319) and `_search_vec()` (line 339) in `mcp/vaultfs/sqlite.py` already JOIN on `documents d` but only SELECT `d.filename, d.title, d.path, d.file_type, d.tags`. Add three columns:

```sql
d.source_kind, d.updated_at, d.date
```

### 1.2 Add scoring multipliers to `_rrf_combine()`

After computing the base RRF score for each chunk, apply two multipliers:

**Recency decay** — exponential decay with configurable half-life:

```python
_RECENCY_HALF_LIFE_DAYS = 180  # 6 months

def _recency_factor(result: dict) -> float:
    doc_date = _parse_date(result.get("date")) or _parse_date(result.get("updated_at"))
    if not doc_date:
        return 0.75  # unknown age gets neutral score
    age_days = (datetime.utcnow() - doc_date).days
    return 0.5 + 0.5 * math.exp(-0.693 * age_days / _RECENCY_HALF_LIFE_DAYS)
```

This produces: today → 1.0, 6 months → 0.75, 2 years → ~0.53. The floor of 0.5 prevents old-but-relevant documents from being buried entirely.

**Source kind boost** — wiki pages represent curated knowledge and get a mild boost:

```python
def _source_kind_factor(result: dict) -> float:
    kind = result.get("source_kind", "source")
    return {"wiki": 1.15, "source": 1.0, "asset": 0.9}.get(kind, 1.0)
```

Apply both after base RRF:

```python
for key in scores:
    scores[key] *= _recency_factor(result_map[key])
    scores[key] *= _source_kind_factor(result_map[key])
```

### 1.3 Files to modify

| File | Change |
|------|--------|
| `mcp/vaultfs/sqlite.py` | Add columns to SELECT in `_search_fts()` and `_search_vec()`. Add `_recency_factor()`, `_source_kind_factor()`, `_parse_date()` helpers. Modify `_rrf_combine()` to apply multipliers. |

### 1.4 Verification

- Unit test `_recency_factor()` with known dates: today (~1.0), 180 days (~0.75), 730 days (~0.53), None (0.75)
- Unit test `_source_kind_factor()`: wiki > source > asset
- Integration test: insert two chunks with identical content but different `source_kind` and `updated_at`, verify wiki/recent one ranks higher
- Regression: existing search tests still pass (multipliers are additive, don't change relative ordering for equal-age/equal-kind results)

---

## Phase 2 — Automated Document Classification

**Goal**: Classify documents into semantic categories at ingestion time without manual tagging. Store in the existing `metadata` JSON column. Use classifications as a third scoring signal.

**Estimated effort**: 2–3 days. Can be done in parallel with Phase 1.

### 2.1 Heuristic classifier

New file: `api/services/classifier.py`

A rule-based classifier that examines filename patterns and the first ~3000 characters of content. Categories:

| Category | Filename signals | Content signals |
|----------|-----------------|-----------------|
| `decision_record` | decision, adr, rfc | "Status: Accepted", "Consequences:", "Context:" |
| `meeting_notes` | meeting, minutes, standup, retro | "Attendees:", "Action items:", "Agenda:" |
| `technical_spec` | spec, design, architecture | "Requirements:", "Specification:", "Interface:" |
| `report` | report, summary, analysis, findings | "Executive summary", "Conclusions:", "Recommendations:" |
| `correspondence` | email, thread, chat | "From:", "To:", "Subject:" (at line start) |
| `reference` | handbook, guide, manual, policy, runbook | "Table of contents", "Chapter N", "Section N" |
| `presentation` | — | (detected by file_type: pptx, ppt) |
| `spreadsheet` | — | (detected by file_type: xlsx, xls) |
| `general` | — | (fallback) |

Scoring: filename match = 3 points, each content pattern match = 1 point. Highest-scoring category wins.

```python
def classify_document(filename: str, file_type: str, content_preview: str) -> str:
    ...
```

### 2.2 Integrate into ingestion paths

Three integration points:

| File | Where |
|------|-------|
| `api/routes/local_upload.py` | After text content is available (line ~70), before INSERT. Call `classify_document()`, store in metadata JSON. |
| `api/domain/local_processor.py` | After async text extraction completes in `_store_page_contents()`. Call classifier on `full_content[:3000]`. |
| `api/domain/watcher.py` | In `_index_file()` after reading content. |

Store as: `metadata = {"doc_category": "decision_record"}`

### 2.3 Backfill existing documents

New function in `api/services/classifier.py`:

```python
async def backfill_categories(db) -> int:
    """Classify all ready documents that lack a doc_category."""
```

Iterates documents where `metadata` doesn't contain `doc_category`, reads `substr(content, 1, 3000)`, classifies, and updates. Call from startup (similar to existing `_backfill_embeddings`).

### 2.4 Category authority weights in RRF

Add `d.metadata` to both search SELECTs. New helper:

```python
_CATEGORY_AUTHORITY = {
    "decision_record": 1.25,
    "technical_spec": 1.20,
    "reference": 1.15,
    "report": 1.10,
    "general": 1.0,
    "presentation": 0.95,
    "meeting_notes": 0.90,
    "spreadsheet": 0.90,
    "correspondence": 0.85,
}

def _category_factor(result: dict) -> float:
    metadata = json.loads(result.get("metadata") or "{}")
    return _CATEGORY_AUTHORITY.get(metadata.get("doc_category", "general"), 1.0)
```

### 2.5 Verification

- Unit test `classify_document()` against each category with representative filenames and content snippets
- Test fallback to `general` for ambiguous content
- Integration test: upload a file named `adr-001-db-choice.md` with ADR content, verify `metadata.doc_category == "decision_record"`
- Test backfill: create documents without categories, run backfill, verify categories assigned

---

## Phase 3 — Metadata-Enriched Embeddings

**Goal**: Prepend document metadata to chunk text before computing embeddings, so vector representations capture document context.

Research ([arXiv 2510.24402](https://arxiv.org/html/2510.24402v1)) shows this yields the largest accuracy gains compared to post-retrieval reranking alone.

**Estimated effort**: 2–3 days. Depends on Phase 2 (needs `doc_category`).

### 3.1 Embedding text builder

New function in `shared/embedder.py`:

```python
def build_embedding_text(
    chunk_content: str,
    title: str | None = None,
    doc_category: str | None = None,
    header_breadcrumb: str | None = None,
    date: str | None = None,
) -> str:
    parts = []
    if title:
        parts.append(f"Document: {title}")
    if doc_category and doc_category != "general":
        parts.append(f"Type: {doc_category.replace('_', ' ').title()}")
    if date:
        parts.append(f"Date: {date}")
    if header_breadcrumb:
        parts.append(f"Section: {header_breadcrumb}")
    prefix = ". ".join(parts)
    return f"{prefix}\n\n{chunk_content}" if prefix else chunk_content
```

### 3.2 Use enriched text at embedding time

In `api/domain/local_processor.py`, the embedding call currently does:

```python
texts = [c.content for c in chunks]
embeddings = embed_texts(texts)
```

Change to:

```python
texts = [
    build_embedding_text(c.content, doc_title, doc_category, c.header_breadcrumb, doc_date)
    for c in chunks
]
embeddings = embed_texts(texts)
```

This requires fetching `title`, `date`, and `metadata.doc_category` from the documents table before embedding.

### 3.3 Re-embedding migration

Existing `chunk_vec` entries become stale since their embeddings were computed from raw text. Options:

1. **Version flag**: Add an `embedding_version INTEGER DEFAULT 1` column to `workspace`. Increment when embedding format changes. On startup, if version mismatches, trigger background re-embedding of all chunks.
2. **One-shot backfill**: Delete all `chunk_vec` rows and re-embed. Similar to existing `_backfill_embeddings` logic.

For large knowledge bases, re-embedding should run in the background to avoid blocking the MCP server.

### 3.4 Verification

- Unit test `build_embedding_text()` with various metadata combinations
- Qualitative test: create a test KB with 5 typed documents, run specific queries, compare top-3 results before/after enrichment
- Verify `chunk_vec` row count matches `document_chunks` after migration

---

## Phase 4 — Configurable Ranking Profiles

**Goal**: Allow per-knowledge-base ranking weight configuration so different workspaces can tune recency vs. authority vs. raw relevance.

**Estimated effort**: 1–2 days. Depends on Phase 1.

### 4.1 Schema change

Add to `workspace` table:

```sql
ALTER TABLE workspace ADD COLUMN ranking_config TEXT DEFAULT '{}';
```

JSON structure:

```json
{
  "recency_half_life_days": 180,
  "recency_floor": 0.5,
  "wiki_boost": 1.15,
  "category_weights": {
    "decision_record": 1.25,
    "meeting_notes": 0.90
  },
  "rrf_k": 60
}
```

### 4.2 RankingProfile dataclass

New file: `mcp/vaultfs/ranking.py`

```python
@dataclass
class RankingProfile:
    recency_half_life_days: float = 180.0
    recency_floor: float = 0.5
    wiki_boost: float = 1.15
    source_boost: float = 1.0
    category_weights: dict[str, float] = field(default_factory=lambda: {...})
    rrf_k: int = 60

    @classmethod
    def from_json(cls, config: dict) -> "RankingProfile": ...

    def recency_factor(self, age_days: float) -> float: ...
    def source_kind_factor(self, kind: str) -> float: ...
    def category_factor(self, category: str) -> float: ...
```

### 4.3 Thread through search pipeline

- `search_chunks()` loads `ranking_config` from workspace, creates `RankingProfile`
- Passes profile to `_rrf_combine()`
- Hardcoded constants from Phase 1 become profile defaults

### 4.4 Verification

- Unit test `RankingProfile.from_json()` with partial overrides
- Integration test: set custom `ranking_config`, verify weights applied
- Backward compatibility: workspaces without `ranking_config` use defaults

---

## Implementation Order & Dependencies

```
Phase 1 (RRF enhancements)     ──┐
                                  ├──→ Phase 4 (configurable profiles)
Phase 2 (classification)  ───────┤
                                  └──→ Phase 3 (enriched embeddings)
```

- Phases 1 and 2 can be done in parallel
- Phase 3 requires Phase 2 (needs `doc_category`)
- Phase 4 requires Phase 1 (parameterizes the scoring functions)

## Key Files Reference

| File | Role |
|------|------|
| `mcp/vaultfs/sqlite.py` | Search pipeline: `_rrf_combine()`, `_search_fts()`, `_search_vec()`, `search_chunks()` |
| `shared/sqlite_schema.sql` | `documents`, `document_chunks`, `document_references` tables |
| `shared/embedder.py` | `embed_texts()`, `embed_query()`, `serialize_embedding()` |
| `api/services/chunker.py` | `chunk_text()`, `chunk_pages()`, `Chunk` dataclass |
| `api/routes/local_upload.py` | Upload ingestion (text documents) |
| `api/domain/local_processor.py` | Async document processing (PDF, Office, etc.) |
| `api/domain/watcher.py` | File watcher ingestion path |

## Research References

- [Solving Freshness in RAG: A Simple Recency Prior (arXiv 2509.19376)](https://arxiv.org/html/2509.19376) — half-life exponential decay
- [Metadata-Driven RAG for Financial QA (arXiv 2510.24402)](https://arxiv.org/html/2510.24402v1) — embedding metadata in chunks yields largest gains
- [How to Prioritize Documents in RAG Systems (CustomGPT)](https://customgpt.ai/prioritize-documents-in-rag-retrieval-process/) — authority and recency rules
- [Rerankers and Two-Stage Retrieval (Pinecone)](https://www.pinecone.io/learn/series/rag/rerankers/) — reranking patterns
- [Retrievals - Recency Bias (Ragie)](https://docs.ragie.ai/docs/retrievals-recency-bias) — time-bucket approach
