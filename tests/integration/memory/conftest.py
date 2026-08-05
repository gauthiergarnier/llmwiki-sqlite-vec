"""Fixtures for the standalone memory MCP server tests.

Uses MemoryStore with a temp workspace and its own memory.db — no Postgres, no
Ollama. The `memory` package is importable because the repo root is on sys.path
during the pytest run (tests/ is a package).
"""

import pytest


@pytest.fixture
async def workspace(tmp_path):
    ws = tmp_path / "workspace"
    (ws / "wiki").mkdir(parents=True)
    (ws / ".llmwiki").mkdir()
    return ws


@pytest.fixture
async def store(workspace):
    from memory.store import MemoryStore
    await MemoryStore.init(str(workspace))
    yield MemoryStore("local")
    await MemoryStore.close()


def make_tools(store):
    """Register the memory tools against a capturing stand-in for FastMCP."""

    class _FakeMCP:
        def __init__(self):
            self.tools = {}

        def tool(self, name=None, description=None):
            def deco(fn):
                self.tools[name or fn.__name__] = fn
                return fn
            return deco

    from memory.tools import register
    mcp = _FakeMCP()
    register(mcp, lambda ctx: "local", lambda uid: store)
    return mcp.tools
