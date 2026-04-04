"""WikiJS MCP Server implementation over HTTP."""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from mcp.server import FastMCP
from mcp.types import TextContent
from .client import WikiJSClient
from .config import WikiJSConfig

logger = logging.getLogger(__name__)


class WikiJSMCPServer:
    """MCP Server for Wiki.js integration over HTTP."""

    def __init__(self):
        self.config = WikiJSConfig.load_config()
        self.app = FastMCP(
            name="wikijs-mcp-server",
            instructions="A Model Context Protocol server for Wiki.js integration",
        )
        self._setup_tools()

    def _setup_tools(self):
        """Setup MCP tools."""

        @self.app.tool(description="Search for pages in the Wiki.js instance")
        async def wiki_search(query: str, limit: int = 10) -> str:
            """Search for pages in Wiki.js.

            Args:
                query: Search query for finding pages
                limit: Maximum number of results (default: 10)
            """
            async with WikiJSClient(self.config) as client:
                results = await client.search_pages(query, limit)

                if not results:
                    return f"No pages found for query: {query}"

                response = f"Found {len(results)} pages for query '{query}':\n\n"
                for page in results:
                    response += f"**{page['title']}**\n"
                    response += f"Path: {page['path']}\n"
                    if page.get("description"):
                        response += f"Description: {page['description']}\n"
                    if page.get("locale"):
                        response += f"Locale: {page['locale']}\n"
                    if page.get("id"):
                        response += f"ID: {page['id']}\n"
                    response += "\n"

                return response

        @self.app.tool(description="Get a specific wiki page by path or ID")
        async def wiki_get_page(
            path: Optional[str] = None, id: Optional[int] = None, locale: str = "en"
        ) -> str:
            """Get a specific wiki page by path or ID.

            Args:
                path: Page path (e.g., 'docs/getting-started'). Use either path OR id, not both.
                id: Page ID. Use either path OR id, not both.
                locale: Page locale (default: 'en'). Only used with path.
            """
            # Validate that exactly one of path or id is provided
            has_path = path is not None
            has_id = id is not None

            if not has_path and not has_id:
                raise ValueError("Either 'path' or 'id' parameter is required")
            if has_path and has_id:
                raise ValueError(
                    "Cannot specify both 'path' and 'id' parameters - use only one"
                )

            async with WikiJSClient(self.config) as client:
                if has_path:
                    page = await client.get_page_by_path(path, locale)
                else:
                    page = await client.get_page_by_id(id)

                if not page:
                    return "Page not found"

                response = f"# {page['title']}\n\n"
                response += f"**Path:** {page['path']}\n"
                response += f"**ID:** {page['id']}\n"
                if page.get("description"):
                    response += f"**Description:** {page['description']}\n"
                response += f"**Editor:** {page.get('editor', 'unknown')}\n"
                response += f"**Locale:** {page.get('locale', 'en')}\n"
                if page.get("authorName"):
                    response += f"**Author:** {page['authorName']}\n"
                response += f"**Created:** {page['createdAt']}\n"
                response += f"**Updated:** {page['updatedAt']}\n"
                if page.get("tags"):
                    tags = [
                        tag.get("tag", tag.get("title", str(tag)))
                        for tag in page["tags"]
                    ]
                    response += f"**Tags:** {', '.join(tags)}\n"
                response += "\n---\n\n"
                response += page.get("content", "")

                return response

        @self.app.tool(description="List all pages")
        async def wiki_list_pages(limit: int = 50) -> str:
            """List all pages.

            Args:
                limit: Number of pages to return (default: 50)
            """
            async with WikiJSClient(self.config) as client:
                pages = await client.list_pages(limit)

                if not pages:
                    return "No pages found"

                response = f"Found {len(pages)} pages (limit: {limit}):\n\n"
                for page in pages:
                    response += f"**{page['title']}**\n"
                    response += f"Path: {page['path']} (ID: {page['id']})\n"
                    if page.get("description"):
                        response += f"Description: {page['description']}\n"
                    response += f"Updated: {page['updatedAt']}\n\n"

                return response

        @self.app.tool(description="Get wiki page tree structure")
        async def wiki_get_tree(
            parent_path: str = "",
            mode: str = "ALL",
            locale: str = "en",
            parent_id: Optional[int] = None,
        ) -> str:
            """Get wiki page tree structure.

            Args:
                parent_path: Parent path to get tree from (default: root)
                mode: Tree mode - ALL, FOLDERS, or PAGES (default: ALL)
                locale: Page locale (default: 'en')
                parent_id: Parent page ID (optional)
            """
            async with WikiJSClient(self.config) as client:
                tree = await client.get_page_tree(parent_path, mode, locale, parent_id)

                if not tree:
                    return "No pages found in tree"

                response = (
                    f"Wiki page tree from '{parent_path or 'root'}' (mode: {mode}):\n\n"
                )
                for item in tree:
                    indent = "  " * item.get("depth", 0)
                    if item.get("isFolder"):
                        response += f"{indent}📁 {item['title']}/\n"
                    else:
                        response += f"{indent}📄 {item['title']} ({item['path']})\n"

                return response

        @self.app.tool(description="Create a new wiki page")
        async def wiki_create_page(
            path: str,
            title: str,
            content: str,
            description: str = "",
            tags: List[str] = None,
        ) -> str:
            """Create a new wiki page.

            Args:
                path: Page path (e.g., 'docs/new-feature')
                title: Page title
                content: Page content in markdown
                description: Page description (optional)
                tags: Page tags (optional)
            """
            if tags is None:
                tags = []

            async with WikiJSClient(self.config) as client:
                result = await client.create_page(
                    path=path,
                    title=title,
                    content=content,
                    description=description,
                    tags=tags,
                )

                page_info = result.get("page", {})
                response = f"✅ Successfully created page:\n\n"
                response += f"**Title:** {page_info.get('title', title)}\n"
                response += f"**Path:** {page_info.get('path', path)}\n"
                response += f"**ID:** {page_info.get('id', 'Unknown')}\n"

                return response

        @self.app.tool(description="Update an existing wiki page")
        async def wiki_update_page(
            id: int,
            content: str,
            title: Optional[str] = None,
            description: Optional[str] = None,
            tags: Optional[List[str]] = None,
        ) -> str:
            """Update an existing wiki page.

            Args:
                id: Page ID to update
                content: New page content in markdown
                title: New page title (optional)
                description: New page description (optional)
                tags: New page tags (optional)
            """
            async with WikiJSClient(self.config) as client:
                result = await client.update_page(
                    page_id=id,
                    content=content,
                    title=title,
                    description=description,
                    tags=tags,
                )

                page_info = result.get("page", {})
                response = f"✅ Successfully updated page:\n\n"
                response += f"**Title:** {page_info.get('title', 'Unknown')}\n"
                response += f"**Path:** {page_info.get('path', 'Unknown')}\n"
                response += f"**ID:** {page_info.get('id', id)}\n"
                response += f"**Updated:** {page_info.get('updatedAt', 'Just now')}\n"

                return response

        @self.app.tool(description="Delete a wiki page")
        async def wiki_delete_page(id: int) -> str:
            """Delete a wiki page by ID.

            Args:
                id: Page ID to delete
            """
            async with WikiJSClient(self.config) as client:
                result = await client.delete_page(page_id=id)

                response = f"✅ Successfully deleted page with ID: {id}\n"
                response_result = result.get("responseResult", {})
                if response_result.get("message"):
                    response += f"**Message:** {response_result['message']}\n"

                return response

        @self.app.tool(description="Move a wiki page to a new path and/or locale")
        async def wiki_move_page(
            id: int, destination_path: str, destination_locale: str = "en"
        ) -> str:
            """Move a wiki page to a new path and/or locale.

            Args:
                id: Page ID to move
                destination_path: New path for the page (e.g., 'docs/moved-page')
                destination_locale: New locale for the page (default: 'en')
            """
            async with WikiJSClient(self.config) as client:
                # Get the current page info for the response
                current_page = await client.get_page_by_id(id)
                if not current_page:
                    return f"❌ Page with ID {id} not found"

                current_path = current_page.get("path", "Unknown")
                current_locale = current_page.get("locale", "Unknown")

                result = await client.move_page(
                    page_id=id,
                    destination_path=destination_path,
                    destination_locale=destination_locale,
                )

                response = f"✅ Successfully moved page:\n\n"
                response += f"**Title:** {current_page.get('title', 'Unknown')}\n"
                response += f"**From:** {current_path} (locale: {current_locale})\n"
                response += (
                    f"**To:** {destination_path} (locale: {destination_locale})\n"
                )
                response += f"**Page ID:** {id}\n"

                response_result = result.get("responseResult", {})
                if response_result.get("message"):
                    response += f"**Message:** {response_result['message']}\n"

                return response

    async def run_stdio(self):
        """Run the MCP server over stdio."""
        try:
            self.config.validate_config()
            logger.info(f"Starting WikiJS MCP Server for {self.config.url}")
            await self.app.run_stdio_async()
        except Exception as e:
            logger.error(f"Server failed to start: {str(e)}")
            raise


async def main():
    """Main entry point."""
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("WikiJS MCP Server")
        print("Usage:")
        print("  python -m wikijs_mcp.server")
        print("  python -m wikijs_mcp.server --help")
        print("")
        print("Runs the MCP server over stdio for use with Claude Code")
        print("and other MCP clients.")
        return

    server = WikiJSMCPServer()
    await server.run_stdio()


if __name__ == "__main__":
    asyncio.run(main())
