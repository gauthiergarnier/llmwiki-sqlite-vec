#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="${WORKSPACE_PATH:-/workspace}"

if [ ! -f "$WORKSPACE/.llmwiki/index.db" ]; then
  python /app/llmwiki init "$WORKSPACE"
fi

# Migrate up-front so the API/MCP startup runners are guaranteed no-ops and a
# slow legacy migration can't outlive the readiness probes below.
python -c "import sys; sys.path.insert(0, '/app/api'); from infra.db.local_migrations import apply_migrations; apply_migrations('$WORKSPACE/.llmwiki/index.db')"

PIDS=()
shutdown() {
  kill -TERM "${PIDS[@]}" 2>/dev/null || true
}
trap shutdown TERM INT

cd /app/api
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 10 &
API_PID=$!
PIDS+=("$API_PID")

READY=0
for _ in $(seq 1 120); do
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=1)" 2>/dev/null; then
    READY=1
    break
  fi
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "API exited during startup" >&2
    exit 1
  fi
  sleep 0.5
done
if [ "$READY" != 1 ]; then
  echo "API failed to become ready within 60s" >&2
  shutdown
  wait || true
  exit 1
fi

cd /app/mcp
/opt/mcp/bin/python -m local_server --workspace "$WORKSPACE" --transport streamable-http --port 8100 &
PIDS+=("$!")

cd /app/web
PORT=3000 HOSTNAME=0.0.0.0 node server.js &
PIDS+=("$!")

EXIT_CODE=0
wait -n "${PIDS[@]}" || EXIT_CODE=$?
shutdown
wait || true
exit "$EXIT_CODE"
