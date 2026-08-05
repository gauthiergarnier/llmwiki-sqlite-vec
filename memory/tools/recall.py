"""`recall` (quick memory) and `history` (why we ended there) tools."""

from mcp.server.fastmcp import FastMCP, Context


def register(mcp: FastMCP, get_user_id, store_factory) -> None:

    @mcp.tool(
        name="recall",
        description=(
            "Quick memory: retrieve the CURRENT, valid claims for a question (facts and decisions "
            "in force right now). Superseded/expired claims are excluded — use `history` for those. "
            "Hybrid keyword + semantic search. Optionally filter by `subject` or `claim_type`."
        ),
    )
    async def recall(
        ctx: Context, query: str, subject: str = "", claim_type: str = "", limit: int = 8,
    ) -> str:
        store = store_factory(get_user_id(ctx))
        results = await store.search_claims(
            query, limit=limit, include_superseded=False,
            claim_type=claim_type.strip() or None, subject=subject.strip() or None,
        )
        if not results:
            return "No current claims match. (Nothing remembered yet, or all superseded.)"
        return "**Quick memory — current claims**\n\n" + "\n\n".join(_fmt_claim(r) for r in results)

    @mcp.tool(
        name="history",
        description=(
            "History: understand WHY we ended where we did. Pass `claim_id` to see a full "
            "supersession chain (A→B→C) with each step's rationale and validity window; pass "
            "`subject` to see the evolution of a topic (including superseded claims); pass `query` "
            "for a semantic search across all claims (current + historical). `as_of` (ISO datetime) "
            "shows what we believed at that point in time (transaction-time travel)."
        ),
    )
    async def history(
        ctx: Context, query: str = "", claim_id: str = "", subject: str = "",
        as_of: str = "", limit: int = 12,
    ) -> str:
        store = store_factory(get_user_id(ctx))
        claim_id, subject, query, as_of = (s.strip() for s in (claim_id, subject, query, as_of))

        if claim_id:
            chain = await store.get_claim_chain(claim_id)
            if not chain:
                return f"No claim found for id `{claim_id}`."
            return _fmt_chain(chain)

        if subject and not query:
            claims = await store.claims_by_subject(subject, include_superseded=True)
            if not claims:
                return f"No claims recorded for subject `{subject}`."
            return (f"**History of `{subject}`** ({len(claims)} claim(s), oldest first)\n\n"
                    + "\n\n".join(_fmt_claim(c, temporal=True) for c in claims))

        results = await store.search_claims(
            query or subject, limit=limit, include_superseded=True,
            subject=subject or None, as_of=as_of or None,
        )
        header = "**History**" + (f" — as of {as_of}" if as_of else " (current + superseded)")
        if not results:
            return header + "\n\nNo matching claims."
        return header + "\n\n" + "\n\n".join(_fmt_claim(r, temporal=True) for r in results)


def _fmt_claim(c: dict, temporal: bool = False) -> str:
    lines = [f"- **`{c['id'][:8]}`** ({c.get('claim_type','fact')}"
             + (f", {c['subject']}" if c.get("subject") else "") + f"): {c['statement']}"]
    if c.get("rationale"):
        lines.append(f"  - why: {c['rationale']}")
    if temporal:
        status = "superseded" if c.get("superseded_by") else ("expired" if c.get("expired_at") else "current")
        win = f"valid {c.get('valid_at','?')}" + (f" → {c['invalid_at']}" if c.get("invalid_at") else " → now")
        lines.append(f"  - {status}; {win}")
        if c.get("superseded_by"):
            lines.append(f"  - superseded by `{c['superseded_by'][:8]}`")
    return "\n".join(lines)


def _fmt_chain(chain: list[dict]) -> str:
    out = [f"**Supersession chain** ({len(chain)} step(s), oldest → newest):\n"]
    for i, c in enumerate(chain):
        arrow = "" if i == 0 else "↳ "
        marker = "✅ current" if (c.get("expired_at") is None and c.get("invalid_at") is None) else "🗄️ retired"
        out.append(f"{arrow}**`{c['id'][:8]}`** [{marker}] — {c['statement']}")
        if c.get("rationale"):
            out.append(f"    why: {c['rationale']}")
        out.append(f"    valid {c.get('valid_at','?')}"
                   + (f" → {c['invalid_at']}" if c.get("invalid_at") else " → now"))
    return "\n".join(out)
