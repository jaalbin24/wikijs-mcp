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
  -- pipx run wikijs-mcp
```

Verify with `claude mcp list`.

### Other MCP clients

Add to your MCP client config:

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

You can substitute `pipx run wikijs-mcp` with `uvx wikijs-mcp` or install globally with `pip install wikijs-mcp` and use `wikijs-mcp` as the command.

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
git clone https://github.com/jaalbin24/wikijs-mcp.git
cd wikijs-mcp
poetry install
poetry run pytest
```

## License

MIT
