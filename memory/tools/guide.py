"""`guide` tool for the memory server — teaches the memory workflow."""

from mcp.server.fastmcp import FastMCP, Context

GUIDE_TEXT = """# LLM Wiki — Memory (bi-temporal)

You are connected to the **Memory** server — a continuously-learning companion to the
LLM Wiki. The wiki holds the *current synthesized state*; Memory holds the *evolving
record of facts and decisions and the reasoning behind them*, so the knowledge base
learns over time instead of just being overwritten.

## Two kinds of recall

- **Quick memory** — `recall(query)` returns only the **current, valid** claims (the
  fast, simple answer). Superseded claims are excluded.
- **History** — `history(claim_id=… | subject=… | query=… | as_of=…)` returns the
  **why we ended there**: supersession chains (A→B→C) with each step's rationale and
  validity window, the evolution of a subject, or what we believed at a past time.

## Recording (continuous learning, not overwriting)

- `remember(statement, rationale, claim_type, subject, supersedes, valid_at)` records a
  durable claim. A claim is a **fact** or a **decision** (also `preference`,
  `observation`). **Always give a `rationale`** — the context and subtleties.
- **Supersede, don't delete.** When a new claim replaces an old one, pass
  `supersedes=<old claim id>`. The old claim is *retained* (queryable via `history`) and
  linked to its replacement. Nothing is ever lost.
- `subject` groups a topic (e.g. `deploy-strategy`) so its history reads as one thread.
- `log_event(summary, detail, kind)` records an episode (ingest / query / decision /
  revision / lint) without a claim.

## The inconsistency check (uncertainty-gated)

If you call `remember` *without* `supersedes`, an inconsistency check runs against
similar current claims:
- A **confident** conflict is reconciled automatically (append-only supersession).
- An **ambiguous / uncertain** one is **not** acted on — it becomes a **clarification**.
  Both claims stay current until the user decides.

Use `clarifications(action="list")` to fetch open clarifications. Each is shaped like an
AskUserQuestion (a question + options) — present it to the user with your AskUserQuestion
UI, then `clarifications(action="resolve", id=…, choice=…)`. The fuzzier the call, the
more it defers to the user.

## When to use which
- Answering a quick factual/decision question → `recall`.
- "Why did we choose X?" / "what changed?" / "what did we think back then?" → `history`.
- Learned something or made/changed a decision → `remember` (with rationale; supersede if
  it replaces something).
- The system flagged a conflict → `clarifications`.

Tools: `guide`, `recall`, `history`, `remember`, `log_event`, `clarifications`, `ping`.
"""


def register(mcp: FastMCP, get_user_id, store_factory) -> None:

    @mcp.tool(
        name="guide",
        description="How the bi-temporal Memory works. Call this first to learn the recall/remember/clarify workflow.",
    )
    async def guide(ctx: Context) -> str:
        return GUIDE_TEXT
