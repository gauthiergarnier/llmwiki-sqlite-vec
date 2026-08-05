"""`remember` / `log_event` tools — the ingestion path with the inconsistency check."""

from mcp.server.fastmcp import FastMCP, Context

from ..config import settings
from ..assessor import ConflictAssessor

REMEMBER_DESC = (
    "Record a durable claim — a fact OR a decision — into bi-temporal memory. "
    "Use this whenever you learn something worth keeping or make/changes a decision.\n\n"
    "Supersede, don't delete: if this replaces an earlier claim, pass `supersedes=<claim id>` — "
    "the old claim is retained in history with its rationale so we never lose 'why we ended there'.\n\n"
    "If you don't pass `supersedes`, an inconsistency check runs: a confident conflict is resolved "
    "automatically, but an ambiguous one is escalated to the user as a clarification (see the "
    "`clarifications` tool). Always include a `rationale` — the why/context/subtleties.\n\n"
    "claim_type: fact | decision | preference | observation. `subject` groups related claims "
    "(e.g. 'deploy-strategy'). `valid_at` is an ISO date for when the claim became true in the world."
)


def register(mcp: FastMCP, get_user_id, store_factory) -> None:

    @mcp.tool(name="remember", description=REMEMBER_DESC)
    async def remember(
        ctx: Context,
        statement: str,
        rationale: str = "",
        claim_type: str = "fact",
        subject: str = "",
        supersedes: str = "",
        valid_at: str = "",
        source_path: str = "",
    ) -> str:
        store = store_factory(get_user_id(ctx))
        statement = statement.strip()
        if not statement:
            return "Error: `statement` is required."
        if claim_type not in ("fact", "decision", "preference", "observation"):
            claim_type = "fact"

        rationale = rationale.strip() or None
        subject = subject.strip() or None
        valid_at = valid_at.strip() or None
        source_path = source_path.strip() or None

        # Candidate conflicts among EXISTING current claims (before adding the new one).
        candidates = await store.similar_current_claims(statement, limit=5)

        episode = await store.record_episode(
            kind="decision" if claim_type == "decision" else "ingest",
            summary=statement[:200],
            detail=rationale,
            source_path=source_path,
        )
        new = await store.add_claim(
            statement, rationale=rationale, claim_type=claim_type, subject=subject,
            valid_at=valid_at, episode_id=episode["id"], source_path=source_path,
        )

        # Claude already decided this supersedes a specific claim → honor it.
        if supersedes.strip():
            await store.supersede_claim(supersedes.strip(), new["id"], invalid_at=valid_at)
            chain = await store.get_claim_chain(new["id"])
            return _fmt_recorded(new, superseded=supersedes.strip(), chain=chain)

        if not candidates:
            return _fmt_recorded(new)

        # Inconsistency check + uncertainty gate.
        decision = await ConflictAssessor(settings).assess(new, candidates)

        if decision.question is not None:
            clar = await store.create_clarification(
                origin="ingestion",
                question=decision.question["question"],
                options={
                    "options": decision.question["options"],
                    "recommended": decision.question.get("recommended", 0),
                },
                candidate_claim_ids=[decision.target_claim_id, new["id"]],
                proposed_action=decision.action,
                confidence=decision.confidence,
                uncertainty_reasons=decision.uncertainty_reasons,
            )
            return _fmt_recorded(new, clarification=clar)

        if (
            decision.action in ("supersede", "merge")
            and decision.target_claim_id
            and decision.confidence >= settings.AUTO_APPLY_THRESHOLD
        ):
            await store.supersede_claim(decision.target_claim_id, new["id"], invalid_at=valid_at)
            chain = await store.get_claim_chain(new["id"])
            return _fmt_recorded(new, superseded=decision.target_claim_id, chain=chain, auto=True)

        return _fmt_recorded(new, related=candidates)

    @mcp.tool(
        name="log_event",
        description=(
            "Record an episode (an event in the decision/work history) without a claim — "
            "e.g. an ingest, a query answered, or a maintenance pass. kind: "
            "ingest | query | decision | revision | lint."
        ),
    )
    async def log_event(
        ctx: Context, summary: str, detail: str = "", kind: str = "query", source_path: str = "",
    ) -> str:
        store = store_factory(get_user_id(ctx))
        if kind not in ("ingest", "query", "decision", "revision", "lint", "consolidation"):
            kind = "query"
        ep = await store.record_episode(
            kind=kind, summary=summary.strip()[:200], detail=detail.strip() or None,
            source_path=source_path.strip() or None,
        )
        return f"Recorded **{kind}** episode `{ep['id'][:8]}`: {ep['summary']}"


def _fmt_recorded(new, *, superseded=None, chain=None, clarification=None, related=None, auto=False) -> str:
    out = [f"Remembered claim `{new['id'][:8]}` ({new['claim_type']}): {new['statement']}"]
    if new.get("rationale"):
        out.append(f"- rationale: {new['rationale']}")
    if superseded:
        verb = "Auto-superseded" if auto else "Superseded"
        out.append(f"- {verb} claim `{superseded[:8]}` (retained in history).")
    if chain and len(chain) > 1:
        out.append("- chain: " + " → ".join(f"`{c['id'][:8]}`" for c in chain))
    if clarification:
        out.append(
            f"\n⚠️ Ambiguous conflict — raised clarification `{clarification['id'][:8]}` "
            "(no claim was superseded). Present it to the user via the `clarifications` tool, "
            "or call `remember` again with an explicit `supersedes=<id>` if you can decide."
        )
    if related:
        out.append("- related current claims (kept, coexisting): "
                   + ", ".join(f"`{c['id'][:8]}`" for c in related[:3]))
    return "\n".join(out)
