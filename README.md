# WikiJS MCP Server

An MCP server that connects MCP clients to your [Wiki.js](https://js.wiki/) instance.

It supports both **local connections over stdio** and **remote connections using the official MCP Streamable HTTP transport**, making it suitable for local MCP clients as well as remotely hosted clients.

## Prerequisites

* Python 3.10+
* A Wiki.js instance with API access enabled
* A Wiki.js API key (`Administration > API Access > New API Key`)

## Installation

```bash
pip install wikijs-mcp
```

For local development:

```bash
git clone https://github.com/Ho3pLi/wikijs-mcp-http.git
cd wikijs-mcp-http
pip install -e .
```

## Configuration

### Wiki.js

| Variable                  | Default    | Description                              |
| ------------------------- | ---------- | ---------------------------------------- |
| `WIKIJS_URL`              | required   | Base URL of your Wiki.js instance        |
| `WIKIJS_API_KEY`          | required   | Wiki.js API key                          |
| `WIKIJS_GRAPHQL_ENDPOINT` | `/graphql` | Wiki.js GraphQL endpoint path            |
| `WIKIJS_READ_ONLY`        | `false`    | When `true`, mutation tools are disabled |

The Wiki.js API key is used only by the MCP server to communicate with Wiki.js. It remains **server-side** and is never returned or exposed to MCP clients.

### Streamable HTTP

| Variable              | Default                                 | Description                             |
| --------------------- | --------------------------------------- | --------------------------------------- |
| `MCP_HOST`            | `127.0.0.1`                             | Host interface for HTTP mode            |
| `MCP_PORT`            | `8000`                                  | Port for HTTP mode                      |
| `MCP_PATH`            | `/mcp`                                  | MCP Streamable HTTP endpoint path       |
| `MCP_ALLOWED_HOSTS`   | `127.0.0.1:*,localhost:*`               | Comma-separated Host header allowlist   |
| `MCP_ALLOWED_ORIGINS` | `http://127.0.0.1:*,http://localhost:*` | Comma-separated Origin header allowlist |

The server intentionally does **not** bind to `0.0.0.0` by default.

For remote deployments, the recommended setup is to keep the MCP server listening locally and expose it through an HTTPS reverse proxy and, when appropriate, an authentication layer.

## Choosing a transport

WikiJS MCP supports two MCP transports.

### stdio

Use `stdio` when the MCP client can start the MCP server locally.

This is typically the simplest option for local clients such as Claude Code or other desktop/development tools.

```text
MCP Client
    │
   stdio
    │
    ▼
WikiJS MCP
    │
  GraphQL
    │
    ▼
 Wiki.js
```

### Streamable HTTP

Use Streamable HTTP when the MCP server needs to run independently or be accessed remotely.

This is useful for hosted MCP clients or when you want to run a single MCP server alongside your Wiki.js infrastructure.

```text
Remote MCP Client
        │
      HTTPS
        │
        ▼
 Reverse Proxy / Auth
        │
        ▼
127.0.0.1:8000/mcp
        │
        ▼
    WikiJS MCP
        │
      GraphQL
        │
        ▼
      Wiki.js
```

Both transports expose the same Wiki.js tools.

## Running

### Local / stdio

`stdio` is the default transport:

```bash
WIKIJS_URL=https://wiki.example.com \
WIKIJS_API_KEY=... \
wikijs-mcp
```

Equivalent explicit form:

```bash
WIKIJS_URL=https://wiki.example.com \
WIKIJS_API_KEY=... \
wikijs-mcp --transport stdio
```

### Remote / Streamable HTTP

```bash
WIKIJS_URL=https://wiki.example.com \
WIKIJS_API_KEY=... \
MCP_HOST=127.0.0.1 \
MCP_PORT=8000 \
MCP_PATH=/mcp \
wikijs-mcp --transport streamable-http
```

This exposes a standards-compliant MCP endpoint at:

```text
http://127.0.0.1:8000/mcp
```

The endpoint is intended to be exposed through HTTPS infrastructure for remote access.

Do not commit credentials or expose the Wiki.js API key to clients.

When deploying behind a reverse proxy with a public hostname, explicitly allow that hostname and its browser origin:

```text
MCP_HOST=127.0.0.1
MCP_PORT=8000
MCP_PATH=/mcp
MCP_ALLOWED_HOSTS=127.0.0.1:*,localhost:*,mcp.example.com
MCP_ALLOWED_ORIGINS=http://127.0.0.1:*,http://localhost:*,https://mcp.example.com
```

The MCP Python SDK enforces DNS rebinding protection for HTTP transports.

Keep that protection enabled. Do not use `*`, disable DNS rebinding protection, or spoof the `Host` header in nginx merely to bypass validation.

## Reverse proxy example

A typical production deployment keeps WikiJS MCP bound to `127.0.0.1` and exposes `/mcp` through a reverse proxy.

Example nginx configuration:

```nginx
server {
    listen 443 ssl;
    server_name mcp.example.com;

    # TLS configuration omitted for brevity.

    location /mcp {
        proxy_pass http://127.0.0.1:8000/mcp;

        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_buffering off;
    }
}
```

With this setup:

```text
https://mcp.example.com/mcp
            │
            ▼
           nginx
            │
            ▼
http://127.0.0.1:8000/mcp
            │
            ▼
        WikiJS MCP
```

Authentication and access control should normally be handled in front of the MCP server when exposing it publicly.

For example, an identity-aware proxy, OAuth-capable gateway, VPN, or equivalent access-control layer can sit between the remote MCP client and nginx/MCP endpoint.

## Read-only mode

WikiJS MCP can expose Wiki.js content without allowing clients to modify it.

Enable read-only mode with:

```bash
WIKIJS_READ_ONLY=true wikijs-mcp --transport streamable-http
```

When enabled, mutation tools return an MCP-visible error before contacting Wiki.js:

* `wiki_create_page`
* `wiki_update_page`
* `wiki_move_page`
* `wiki_delete_page`

Read-only tools continue to work normally.

This can be useful when exposing a Wiki.js knowledge base to remote or third-party MCP clients that should only be able to retrieve information.

## MCP client examples

### Claude Code / stdio

```bash
claude mcp add wikijs \
  --scope user \
  -e WIKIJS_URL=https://your-wiki.com \
  -e WIKIJS_API_KEY=your-api-key \
  -- pipx run wikijs-mcp
```

### Generic stdio client

```json
{
  "mcpServers": {
    "wikijs": {
      "command": "pipx",
      "args": ["run", "wikijs-mcp"],
      "env": {
        "WIKIJS_URL": "https://your-wiki.com",
        "WIKIJS_API_KEY": "your-api-key"
      }
    }
  }
}
```

### Remote MCP clients

Clients that support MCP Streamable HTTP can connect to the public endpoint exposed by your reverse proxy:

```text
https://mcp.example.com/mcp
```

The exact configuration depends on the MCP client being used.

The remote client does **not** need access to the Wiki.js API key. Authentication to Wiki.js is handled entirely by the WikiJS MCP server.

## Tools

| Tool                 | Description                                                                        |
| -------------------- | ---------------------------------------------------------------------------------- |
| `wiki_search`        | Full-text search across all wiki pages                                             |
| `wiki_get_page`      | Get a page by path or ID, with optional `metadata_only` and `include_render` modes |
| `wiki_list_pages`    | List pages with optional tag filtering and sort order                              |
| `wiki_get_tree`      | Get the hierarchical folder/page tree structure                                    |
| `wiki_create_page`   | Create a new page                                                                  |
| `wiki_update_page`   | Update a page via full replacement or surgical find-and-replace (`edits`)          |
| `wiki_move_page`     | Move a page to a new path and/or locale                                            |
| `wiki_delete_page`   | Delete a page                                                                      |
| `wiki_list_tags`     | List all tags used across the wiki                                                 |
| `wiki_get_site_info` | Get wiki site metadata (title, description, host)                                  |
| `wiki_get_history`   | Get page edit history with pagination                                              |
| `wiki_get_version`   | Retrieve a specific historical version of a page                                   |

## Security considerations

When using Streamable HTTP:

* Keep the MCP server bound to `127.0.0.1` unless you specifically need otherwise.
* Use HTTPS for remote access.
* Put authentication or access control in front of publicly reachable MCP endpoints.
* Keep `MCP_ALLOWED_HOSTS` and `MCP_ALLOWED_ORIGINS` restricted to expected hosts and origins.
* Keep DNS rebinding protection enabled.
* Never expose the Wiki.js API key to MCP clients.
* Consider enabling `WIKIJS_READ_ONLY=true` when write access is not required.

The MCP server acts as the trusted intermediary between MCP clients and the Wiki.js GraphQL API.

## Development

```bash
pip install -e .
pip install pytest pytest-asyncio pytest-cov pytest-mock pytest-xdist ruff

pytest
ruff check .
```

## License

MIT
