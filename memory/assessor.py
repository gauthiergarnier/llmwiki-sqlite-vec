"""ConflictAssessor — the uncertainty-gated decision maker.

Used by BOTH the ingestion path (`remember`) and background consolidation.
Given a new/changed claim and its most-similar current claims, it returns a
decision with a confidence. The caller applies the gate:

    confidence >= AUTO_APPLY_THRESHOLD  -> auto-apply (append-only)
    confidence <  AUTO_APPLY_THRESHOLD  -> raise an AskUserQuestion-style
                                            clarification; leave claims untouched

The LLM (Ollama) is used when an `llm_chat` callable is supplied; otherwise the
assessor falls back to an embedding-similarity heuristic that defers to the user
whenever two claims look like near-duplicates (so we never auto-supersede on a
guess). `question` is shaped exactly like the AskUserQuestion tool so the
`clarifications` MCP tool can present it with no translation.
"""

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Decision:
    action: str                      # 'add' | 'supersede' | 'merge' | 'noop'
    confidence: float
    target_claim_id: str | None = None
    uncertainty_reasons: list[str] = field(default_factory=list)
    question: dict | None = None     # AskUserQuestion-shaped, only when escalating


_SYSTEM = (
    "You reconcile a knowledge base of atomic claims. Given a NEW claim and a list "
    "of EXISTING current claims on a related topic, decide the relationship. "
    "Respond ONLY with JSON: {\"action\": one of [add, supersede, noop], "
    "\"target_index\": integer index into existing (or null), \"confidence\": 0.0-1.0, "
    "\"reasons\": [short strings]}. "
    "Use 'supersede' when the new claim makes a specific existing claim no longer true "
    "(a decision changed, a fact was corrected). Use 'noop' when the new claim duplicates "
    "an existing one. Use 'add' when it is genuinely new/complementary. Be honest about "
    "confidence: if the relationship is ambiguous or you are guessing, give LOW confidence."
)


class ConflictAssessor:
    def __init__(self, settings, llm_chat=None):
        self.settings = settings
        self._llm_chat = llm_chat  # async (messages) -> str|None ; injectable for tests

    async def assess(self, new_claim: dict, candidates: list[dict]) -> Decision:
        if not candidates:
            return Decision(action="add", confidence=1.0)

        decision = None
        if self._llm_chat is not None:
            decision = await self._assess_llm(new_claim, candidates)
        if decision is None:
            decision = self._assess_heuristic(candidates)

        gate = self.settings.AUTO_APPLY_THRESHOLD
        # Escalate whenever we're below the gate AND there is a plausible conflict to resolve.
        top = max(candidates, key=lambda c: c.get("similarity", 0.0))
        if decision.confidence < gate and (
            decision.action in ("supersede", "merge")
            or top.get("similarity", 0.0) >= self.settings.DUPLICATE_SIMILARITY_FLOOR
        ):
            target = self._resolve_target(decision, candidates, top)
            decision.target_claim_id = target["id"]
            decision.question = self._build_question(new_claim, target, decision)
        return decision

    # ------------------------------------------------------------------ LLM
    async def _assess_llm(self, new_claim: dict, candidates: list[dict]) -> Decision | None:
        listing = "\n".join(
            f"[{i}] ({c.get('claim_type','fact')}) {c['statement']}"
            + (f"  — rationale: {c['rationale']}" if c.get("rationale") else "")
            for i, c in enumerate(candidates)
        )
        user = (
            f"NEW claim ({new_claim.get('claim_type','fact')}): {new_claim['statement']}"
            + (f"\nNEW rationale: {new_claim['rationale']}" if new_claim.get("rationale") else "")
            + f"\n\nEXISTING current claims:\n{listing}"
        )
        raw = await self._llm_chat(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]
        )
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Assessor LLM returned non-JSON; falling back")
            return None
        action = str(data.get("action", "add")).lower()
        if action not in ("add", "supersede", "noop", "merge"):
            action = "add"
        conf = float(data.get("confidence", 0.0) or 0.0)
        conf = min(max(conf, 0.0), 1.0)
        target_id = None
        ti = data.get("target_index")
        if isinstance(ti, int) and 0 <= ti < len(candidates):
            target_id = candidates[ti]["id"]
        reasons = [str(r) for r in (data.get("reasons") or [])][:5]
        return Decision(action=action, confidence=conf, target_claim_id=target_id,
                        uncertainty_reasons=reasons)

    # ------------------------------------------------------------ heuristic
    def _assess_heuristic(self, candidates: list[dict]) -> Decision:
        top = max(candidates, key=lambda c: c.get("similarity", 0.0))
        sim = top.get("similarity", 0.0)
        if sim >= self.settings.DUPLICATE_SIMILARITY_FLOOR:
            # Near-duplicate / likely conflict, but without an LLM we can't tell
            # supersede from coexistence — defer to the user (low confidence).
            return Decision(
                action="supersede", confidence=0.4, target_claim_id=top["id"],
                uncertainty_reasons=[
                    f"high textual similarity ({sim:.2f}) to an existing claim, "
                    "but supersede-vs-coexist is unclear without the local LLM",
                ],
            )
        return Decision(action="add", confidence=0.95)

    # ------------------------------------------------------------ question
    def question_for(self, new_claim: dict, target_claim: dict, decision: Decision) -> dict:
        """Public builder — used by consolidation to phrase a clarification."""
        return self._build_question(new_claim, target_claim, decision)

    def _resolve_target(self, decision: Decision, candidates: list[dict], top: dict) -> dict:
        if decision.target_claim_id:
            for c in candidates:
                if c["id"] == decision.target_claim_id:
                    return c
        return top

    def _build_question(self, new_claim: dict, target: dict, decision: Decision) -> dict:
        reasons = "; ".join(decision.uncertainty_reasons) or "the relationship is ambiguous"
        return {
            "question": (
                "A new claim looks related to one I already hold — how should I reconcile them?\n\n"
                f"NEW: {new_claim['statement']}\n"
                f"EXISTING: {target['statement']}\n\n"
                f"(Uncertain because {reasons}.)"
            ),
            "recommended": 0 if decision.action in ("supersede", "merge") else 1,
            "options": [
                {
                    "label": "Supersede the existing claim",
                    "description": f"Retire \"{target['statement']}\" — the new claim replaces it. "
                                   "The old claim stays in history with its rationale.",
                    "action": {"type": "supersede", "old_id": target["id"], "new_id": new_claim["id"]},
                },
                {
                    "label": "Keep both",
                    "description": "They coexist — both remain current (e.g. different scope/context).",
                    "action": {"type": "keep_both"},
                },
            ],
            "uncertainty": round(1.0 - decision.confidence, 2),
            "reasons": decision.uncertainty_reasons,
        }
