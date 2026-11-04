# LLM Wiki — local Docker image

One container, one port, one folder. The mounted folder is the workspace: your
markdown lives in it as plain files, the SQLite index lives in `.llmwiki/` inside it.

```bash
docker build -f docker/local/Dockerfile -t llmwiki .
docker run -p 127.0.0.1:3000:3000 -v ~/my-wiki:/workspace llmwiki
```

Open http://localhost:3000. First boot initializes the workspace (and indexes any
files already in the folder); every boot applies pending schema migrations from
`shared/sqlite_migrations/` before serving.

## What runs inside

| Process | Port (internal) | Role |
|---------|-----------------|------|
| FastAPI (`api/`) | 8000 | REST API, SQLite index, file watcher |
| MCP server (`mcp/`) | 8100 | Streamable-HTTP MCP endpoint |
| Next.js standalone (`web/`) | 3000 (exposed) | UI; proxies `/api/*` and `/mcp` to the two above |

Only port 3000 is exposed. The container exits if any process dies.

## MCP

Networked MCP hosts connect to `http://localhost:3000/mcp` (streamable HTTP).
For stdio hosts (Claude Desktop) against a source checkout, `./llmwiki mcp-config <workspace>`
still prints the config snippet.

The endpoint is unauthenticated, same as the rest of local mode. Keep the port
bound to `127.0.0.1` as shown; a bare `-p 3000:3000` publishes it to your whole network.

## Using a different port

The API only accepts browser requests whose `Origin` matches `APP_URL`
(default `http://localhost:3000`), and only loopback origins are allowed. To remap
the port, pass the new loopback URL explicitly:

```bash
docker run -p 127.0.0.1:8080:3000 -e APP_URL=http://localhost:8080 \
  -e API_URL=http://localhost:8080/api -v ~/my-wiki:/workspace llmwiki
```

The Chrome extension's local server URL is `http://localhost:3000/api` (or your remapped port).

## File ownership on Linux

The container runs as root, so files it creates in the bind mount are
root-owned on Linux hosts. Run with your own uid to keep the workspace yours:

```bash
docker run -u "$(id -u):$(id -g)" -p 127.0.0.1:3000:3000 -v ~/my-wiki:/workspace llmwiki
```

## Upgrading

Pull/build the new image and restart the container. Migrations run automatically;
schema state is tracked in `PRAGMA user_version` inside the workspace's `index.db`.
