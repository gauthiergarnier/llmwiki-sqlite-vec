"""`clarifications` tool — surface and resolve uncertain auto-decisions.

Open clarifications are AskUserQuestion-shaped: present them to the user with your
AskUserQuestion UI, then call this tool with action="resolve" and their choice.
"""

import json

from mcp.server.fastmcp import FastMCP, Context


def register(mcp: FastMCP, get_user_id, store_factory) -> None:

    @mcp.tool(
        name="clarifications",
        description=(
            "List or resolve pending memory clarifications — conflicts the system was not "
            "confident enough to resolve on its own.\n"
            "- action=\"list\": show open clarifications (each is an AskUserQuestion: a question + "
            "options). Present them to the user and collect their choice.\n"
            "- action=\"resolve\": apply the user's decision. Pass `id` and `choice` (the option "
            "label or its 0-based index). Resolution is append-only and reversible."
        ),
    )
    async def clarifications(
        ctx: Context, action: str = "list", id: str = "", choice: str = "",
    ) -> str:
        store = store_factory(get_user_id(ctx))

        if action == "resolve":
            if not id.strip() or not choice.strip():
                return "Error: resolve requires both `id` and `choice`."
            res = await store.resolve_clarification(id.strip(), choice.strip())
            if res is None:
                return f"Could not resolve `{id}` — unknown id or invalid choice."
            return f"✅ Resolved clarification `{id[:8]}` → {res.get('resolution')}."

        items = await store.list_clarifications("open")
        if not items:
            return "No open clarifications. Memory is consistent. 🎉"
        return _fmt_clarifications(items)


def _fmt_clarifications(items: list[dict]) -> str:
    out = [f"**{len(items)} open clarification(s)** — present each to the user, then resolve:\n"]
    for it in items:
        opts = it.get("options")
        if isinstance(opts, str):
            try:
                opts = json.loads(opts)
            except json.JSONDecodeError:
                opts = {}
        option_list = (opts or {}).get("options", [])
        recommended = (opts or {}).get("recommended", 0)
        out.append(f"### `{it['id']}`  ({it['origin']}, confidence {it.get('confidence')})")
        out.append(it["question"])
        for idx, o in enumerate(option_list):
            star = " ⭐" if idx == recommended else ""
            out.append(f"  [{idx}] **{o.get('label')}**{star} — {o.get('description','')}")
        out.append(f"  → resolve with: `clarifications(action=\"resolve\", id=\"{it['id']}\", choice=\"0\")`\n")
    return "\n".join(out)
