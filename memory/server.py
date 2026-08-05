"""Standalone MCP server for the bi-temporal MEMORY layer (stdio).

Runs ALONGSIDE the wiki server (mcp/local_server.py), against the same workspace,
but owns its own database (.llmwiki/memory.db) and never writes the wiki index.

Usage (from the repo root):
    python -m memory.server --workspace ~/research
    python -m memory.server ~/research
"""

import argparse
import asyncio
import logging
import os
import uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("llmwiki.memory")

_LOCAL_USER_ID = os.environ.get("LLMWIKI_USER_ID", str(uuid.uuid5(uuid.NAMESPACE_DNS, "local")))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM Wiki memory MCP server")
    parser.add_argument("workspace", nargs="?", default=".", help="Path to workspace folder")
    parser.add_argument("--workspace", dest="workspace_flag", default=None, help="Path to workspace folder")
    return parser.parse_args()


def main():
    args = _parse_args()
    workspace = str(Path(args.workspace_flag or args.workspace).resolve())

    from .store import MemoryStore

    loop = asyncio.new_event_loop()
    loop.run_until_complete(MemoryStore.init(workspace))

    from mcp.server.fastmcp import FastMCP
    from .tools import register

    mcp = FastMCP(
        name="LLM Wiki Memory",
        instructions=(
            "Bi-temporal memory for the LLM Wiki. Use `recall` for quick answers (current "
            "facts/decisions), `history` to understand why we ended where we did, `remember` to "
            "record facts/decisions (supersede, don't delete), and `clarifications` to resolve "
            "conflicts the system was unsure about. Call `guide` first."
        ),
    )

    def _get_user_id(ctx):
        return _LOCAL_USER_ID

    register(mcp, _get_user_id, lambda user_id: MemoryStore(user_id))

    @mcp.tool(name="ping", description="Test connectivity to the memory server")
    async def ping() -> str:
        return "pong (memory)"

    logger.info("Memory MCP server ready — workspace: %s", workspace)
    asyncio.run(mcp.run_stdio_async())


if __name__ == "__main__":
    main()
