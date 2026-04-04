# WikiJS MCP Server

An MCP server that connects Claude to your [Wiki.js](https://js.wiki/) instance. Search, read, create, update, move, and delete wiki pages through natural language.

## Prerequisites

- Python 3.10+
- A Wiki.js instance with API access enabled
- A Wiki.js API key (Administration > API Access > New API Key)

## Installation

### Claude Code

```bash
claude mcp add wikijs \
  -e WIKIJS_URL=https://your-wiki.com \
  -e WIKIJS_API_KEY=your-api-key \
  -- python -m wikijs_mcp.server
```

Verify with `claude mcp list`.

### Manual Configuration

Add to your MCP client config:

```json
{
  "mcpServers": {
    "wikijs": {
      "command": "python",
      "args": ["-m", "wikijs_mcp.server"],
      "env": {
        "WIKIJS_URL": "https://your-wiki.com",
        "WIKIJS_API_KEY": "your-api-key"
      }
    }
  }
}
```

In both cases, you'll need the package installed first:

```bash
pip install -e .
```

## Tools

| Tool | Description |
|------|-------------|
| `wiki_search` | Search pages by title or content |
| `wiki_get_page` | Get a page by path or ID |
| `wiki_list_pages` | List all pages |
| `wiki_get_tree` | Get the page tree structure |
| `wiki_create_page` | Create a new page |
| `wiki_update_page` | Update an existing page |
| `wiki_move_page` | Move a page to a new path |
| `wiki_delete_page` | Delete a page |

## Development

```bash
pip install -e ".[dev]"
pytest
pytest --cov=wikijs_mcp
black wikijs_mcp/ tests/
mypy wikijs_mcp/
```

## License

MIT
