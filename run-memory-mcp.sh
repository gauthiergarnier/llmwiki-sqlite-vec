#!/bin/bash
# Standalone memory MCP server — runs alongside run-mcp.sh against the same workspace.
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
exec "$DIR/.venv/bin/python3" -m memory.server "$@"
