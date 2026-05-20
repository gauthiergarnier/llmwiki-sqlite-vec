#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR/mcp"
exec "$DIR/.venv/bin/python3" -m local_server "$@"
