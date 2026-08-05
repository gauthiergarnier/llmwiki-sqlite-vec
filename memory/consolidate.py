"""Background "sleep-time" consolidation job (Ollama-backed, off the hot path).

Runs the same ConflictAssessor + uncertainty gate as ingestion, but autonomously:

  - Contradiction sweep over current claims. For each plausibly-related pair the
    local LLM judges whether the newer claim supersedes the older.
      * confidence >= AUTO_APPLY_THRESHOLD (mode=auto) -> append-only supersession
      * otherwise (or mode=review)                     -> raise a clarification
  - Subject summaries: a short per-subject digest of current claims.

Degrades gracefully: if Ollama is unreachable it logs and exits without touching
anything. Schedule via launchd/cron, or run manually:

    python -m memory.consolidate ~/research
"""

import argparse
import asyncio
import logging

from .assessor import ConflictAssessor
from .config import settings
from .llm import ollama_available, ollama_chat
from .store import MemoryStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("llmwiki.memory.consolidate")


def _make_llm(cfg):
    async def _chat(messages):
        return await ollama_chat(
            messages, model=cfg.OLLAMA_MODEL, url=cfg.OLLAMA_URL, timeout=cfg.OLLAMA_TIMEOUT_S,
        )
    return _chat


async def run_consolidation(workspace: str, cfg=settings) -> dict:
    await MemoryStore.init(workspace)
    store = MemoryStore("local")
    try:
        if not await ollama_available(cfg.OLLAMA_URL):
            logger.warning("Ollama not reachable at %s — skipping consolidation.", cfg.OLLAMA_URL)
            return {"skipped": "ollama_unreachable", "auto": 0, "clarified": 0, "pairs": 0}

        assessor = ConflictAssessor(cfg, llm_chat=_make_llm(cfg))
        summary = await _contradiction_sweep(store, assessor, cfg)
        await _subject_summaries(store, _make_llm(cfg), cfg)

        await store.record_episode(
            kind="consolidation", actor="consolidation",
            summary=(f"Consolidation: {summary['pairs']} pairs examined, "
                     f"{summary['auto']} auto-superseded, {summary['clarified']} escalated."),
            detail=f"mode={cfg.CONSOLIDATION_MODE}, threshold={cfg.AUTO_APPLY_THRESHOLD}",
        )
        logger.info("Consolidation done: %s", summary)
        return summary
    finally:
        await MemoryStore.close()


async def _contradiction_sweep(store: MemoryStore, assessor: ConflictAssessor, cfg) -> dict:
    current = await store.all_current_claims()
    superseded: set[str] = set()
    processed: set[frozenset] = set()
    stats = {"pairs": 0, "auto": 0, "clarified": 0}

    for c in current:
        if c["id"] in superseded:
            continue
        cands = await store.similar_current_claims(c["statement"], limit=4, exclude_id=c["id"])
        for cand in cands:
            if cand["id"] in superseded:
                continue
            if cand.get("similarity", 0.0) < cfg.CONSOLIDATION_CONSIDER_FLOOR:
                continue
            pair = frozenset((c["id"], cand["id"]))
            if pair in processed:
                continue
            processed.add(pair)

            newer, older = (c, cand) if (c["created_at"] or "") >= (cand["created_at"] or "") else (cand, c)
            decision = await assessor.assess(newer, [older])
            stats["pairs"] += 1
            if decision.action not in ("supersede", "merge"):
                continue

            auto = cfg.CONSOLIDATION_MODE == "auto" and decision.confidence >= cfg.AUTO_APPLY_THRESHOLD
            if auto:
                await store.supersede_claim(older["id"], newer["id"])
                superseded.add(older["id"])
                await store.record_episode(
                    kind="consolidation", actor="consolidation",
                    summary=f"Auto-superseded `{older['id'][:8]}` by `{newer['id'][:8]}`",
                    detail="; ".join(decision.uncertainty_reasons) or "high-confidence contradiction",
                )
                stats["auto"] += 1
            else:
                q = decision.question or assessor.question_for(newer, older, decision)
                await store.create_clarification(
                    origin="consolidation",
                    question=q["question"],
                    options={"options": q["options"], "recommended": q.get("recommended", 0)},
                    candidate_claim_ids=[older["id"], newer["id"]],
                    proposed_action=decision.action,
                    confidence=decision.confidence,
                    uncertainty_reasons=decision.uncertainty_reasons,
                )
                stats["clarified"] += 1
    return stats


async def _subject_summaries(store: MemoryStore, llm, cfg) -> None:
    """Generate a short digest per subject with >1 current claim (best-effort)."""
    current = await store.all_current_claims()
    subjects: dict[str, list[dict]] = {}
    for c in current:
        if c.get("subject"):
            subjects.setdefault(c["subject"], []).append(c)
    for subject, claims in subjects.items():
        if len(claims) < 2:
            continue
        listing = "\n".join(f"- {c['statement']}" for c in claims)
        raw = await llm([
            {"role": "system", "content": "Summarize these current claims into 1-2 sentences. Plain text only."},
            {"role": "user", "content": f"Subject: {subject}\n{listing}"},
        ])
        if raw:
            await store.record_episode(
                kind="consolidation", actor="consolidation",
                summary=f"Summary[{subject}]: {raw.strip()[:240]}",
            )


def main():
    parser = argparse.ArgumentParser(description="LLM Wiki memory consolidation")
    parser.add_argument("workspace", nargs="?", default=".", help="Path to workspace folder")
    args = parser.parse_args()
    from pathlib import Path
    asyncio.run(run_consolidation(str(Path(args.workspace).resolve())))


if __name__ == "__main__":
    main()
