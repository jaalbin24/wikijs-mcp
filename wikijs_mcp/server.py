"""WikiJS MCP Server."""

import asyncio
import logging

from mcp.server import FastMCP

from .client import WikiJSClient
from .config import WikiJSConfig

logger = logging.getLogger(__name__)


class WikiJSMCPServer:
    """MCP Server for Wiki.js integration."""

    def __init__(self):
        self.config = WikiJSConfig.load_config()
        self.app = FastMCP(
            name="wikijs-mcp-server",
            instructions=(
                "Wiki.js MCP server — workflow guidance:\n"
                "- Start by calling wiki_list_pages or wiki_get_tree to orient yourself.\n"
                "- wiki_list_pages returns a flat list with metadata, tags, and content type "
                "(good for filtering by tags or finding recent pages).\n"
                "- wiki_get_tree returns hierarchical folder structure "
                "(good for understanding page organization).\n"
                "- To read a page, use wiki_get_page with its path (human-friendly) or numeric ID "
                "(from list/search results).\n"
                "- Pages are identified by path for reading and by numeric ID for mutations "
                "(update, delete, move).\n"
                "- wiki_update_page supports surgical find-and-replace edits via the 'edits' "
                "parameter — prefer this over full content replacement for small changes.\n"
                "- Use metadata_only=True on wiki_get_page to fetch page info without content, "
                "saving context tokens during exploration.\n"
                "- Use wiki_list_tags to discover available tags, then filter wiki_list_pages by tag."
            ),
        )
        self._setup_tools()

    def _setup_tools(self):
        """Setup MCP tools."""

        @self.app.tool(
            description="Full-text search across all wiki pages. Returns matching page titles, paths, and descriptions. Use this when you know keywords but not the page location."
        )
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

        @self.app.tool(
            description="Retrieve a single wiki page by its path or numeric ID. Returns full content plus metadata (title, tags, editor, content type, dates). Use path for human-readable lookups, ID for follow-ups from list/search results. Set metadata_only=True to skip content and save context tokens."
        )
        async def wiki_get_page(
            path: str | None = None,
            id: int | None = None,
            locale: str = "en",
            metadata_only: bool = False,
            include_render: bool = False,
        ) -> str:
            """Get a specific wiki page by path or ID.

            Args:
                path: Page path (e.g., 'docs/getting-started'). Use either path OR id, not both.
                id: Page ID. Use either path OR id, not both.
                locale: Page locale (default: 'en'). Only used with path.
                metadata_only: If True, skip page content to save context tokens (default: False).
                include_render: If True, include rendered HTML output (default: False).
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
                    page = await client.get_page_by_path(
                        path,
                        locale,
                        metadata_only=metadata_only,
                        include_render=include_render,
                    )
                else:
                    page = await client.get_page_by_id(
                        id, metadata_only=metadata_only, include_render=include_render
                    )

                if not page:
                    return "Page not found"

                response = f"# {page['title']}\n\n"
                response += f"**Path:** {page['path']}\n"
                response += f"**ID:** {page['id']}\n"
                if page.get("description"):
                    response += f"**Description:** {page['description']}\n"
                response += f"**Editor:** {page.get('editor', 'unknown')}\n"
                if page.get("contentType"):
                    response += f"**Content Type:** {page['contentType']}\n"
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
                if not metadata_only:
                    response += "\n---\n\n"
                    response += page.get("content", "")

                if page.get("render"):
                    response += "\n\n---\n**Rendered HTML:**\n\n"
                    response += page["render"]

                return response

        @self.app.tool(
            description="List wiki pages with optional tag filtering and sort order. Returns page metadata (including tags and content type) without content. Use this to discover what pages exist. Supports filtering by tags (AND logic) and ordering by CREATED, ID, PATH, TITLE, or UPDATED."
        )
        async def wiki_list_pages(
            limit: int = 50,
            tags: list[str] | None = None,
            order_by: str = "TITLE",
            order_by_direction: str = "ASC",
        ) -> str:
            """List wiki pages with optional filtering and ordering.

            Args:
                limit: Number of pages to return (default: 50)
                tags: Filter by tags — only pages with ALL specified tags are returned (optional)
                order_by: Sort field — CREATED, ID, PATH, TITLE, or UPDATED (default: TITLE)
                order_by_direction: Sort direction — ASC or DESC (default: ASC)
            """
            valid_order_by = {"CREATED", "ID", "PATH", "TITLE", "UPDATED"}
            if order_by not in valid_order_by:
                raise ValueError(
                    f"Invalid order_by value '{order_by}'. Must be one of: {', '.join(sorted(valid_order_by))}"
                )
            valid_directions = {"ASC", "DESC"}
            if order_by_direction not in valid_directions:
                raise ValueError(
                    f"Invalid order_by_direction value '{order_by_direction}'. Must be one of: {', '.join(sorted(valid_directions))}"
                )

            async with WikiJSClient(self.config) as client:
                pages = await client.list_pages(
                    limit,
                    tags=tags,
                    order_by=order_by,
                    order_by_direction=order_by_direction,
                )

                if not pages:
                    return "No pages found"

                response = f"Found {len(pages)} pages (limit: {limit}):\n\n"
                for page in pages:
                    response += f"**{page['title']}**\n"
                    response += f"Path: {page['path']} (ID: {page['id']})\n"
                    if page.get("description"):
                        response += f"Description: {page['description']}\n"
                    if page.get("contentType"):
                        response += f"Content Type: {page['contentType']}\n"
                    if page.get("tags"):
                        response += f"Tags: {', '.join(page['tags'])}\n"
                    response += f"Updated: {page['updatedAt']}\n\n"

                return response

        @self.app.tool(
            description="Get the hierarchical folder/page tree structure starting from a given path. Use this instead of list_pages when you need to understand how pages are organized in folders. Returns depth-indented entries showing folders and pages."
        )
        async def wiki_get_tree(
            parent_path: str = "",
            mode: str = "ALL",
            locale: str = "en",
            parent_id: int | None = None,
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

        @self.app.tool(
            description="Create a new wiki page at the specified path. Content should match the wiki's editor format (usually markdown). The page path determines its location in the wiki hierarchy (e.g., 'team/onboarding' creates under 'team')."
        )
        async def wiki_create_page(
            path: str,
            title: str,
            content: str,
            description: str = "",
            tags: list[str] = None,
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
                response = "✅ Successfully created page:\n\n"
                response += f"**Title:** {page_info.get('title', title)}\n"
                response += f"**Path:** {page_info.get('path', path)}\n"
                response += f"**ID:** {page_info.get('id', 'Unknown')}\n"

                return response

        @self.app.tool(
            description="Update an existing wiki page by its numeric ID. Supports two content-editing modes: (1) full replacement via 'content', or (2) surgical find-and-replace via 'edits' — a list of {old_text, new_text} pairs applied sequentially. Prefer 'edits' for small, targeted changes to avoid rewriting the entire page. Title, description, and tags can also be updated independently."
        )
        async def wiki_update_page(
            id: int,
            content: str | None = None,
            edits: list[dict] | None = None,
            title: str | None = None,
            description: str | None = None,
            tags: list[str] | None = None,
        ) -> str:
            """Update an existing wiki page.

            Supports two modes for changing content:
            - Full replace: provide 'content' with the entire new page body.
            - Find-and-replace: provide 'edits' as a list of
              {"old_text": "...", "new_text": "..."} pairs. Each old_text is
              replaced with new_text in the existing page content.

            Use 'edits' for small changes to avoid regenerating the full page.
            Do not provide both 'content' and 'edits'.

            Args:
                id: Page ID to update
                content: Full replacement content in markdown (optional)
                edits: List of find-and-replace edits (optional)
                title: New page title (optional)
                description: New page description (optional)
                tags: New page tags (optional)
            """
            if content is not None and edits is not None:
                raise ValueError(
                    "Cannot specify both 'content' and 'edits' — use one or the other"
                )

            applied_edits = []

            if edits is not None:
                async with WikiJSClient(self.config) as client:
                    current_page = await client.get_page_by_id(id)
                    if not current_page:
                        return f"Page with ID {id} not found"

                    current_content = current_page.get("content", "")

                    for edit in edits:
                        old_text = edit.get("old_text", "")
                        new_text = edit.get("new_text", "")

                        if not old_text:
                            raise ValueError(
                                "Each edit must have a non-empty 'old_text'"
                            )

                        if old_text not in current_content:
                            raise ValueError(
                                f"old_text not found in page content: {old_text[:80]!r}"
                            )

                        current_content = current_content.replace(old_text, new_text, 1)
                        applied_edits.append((old_text, new_text))

                    content = current_content

            async with WikiJSClient(self.config) as client:
                result = await client.update_page(
                    page_id=id,
                    content=content,
                    title=title,
                    description=description,
                    tags=tags,
                )

                page_info = result.get("page", {})
                response = "Successfully updated page:\n\n"
                response += f"**Title:** {page_info.get('title', 'Unknown')}\n"
                response += f"**Path:** {page_info.get('path', 'Unknown')}\n"
                response += f"**ID:** {page_info.get('id', id)}\n"
                response += f"**Updated:** {page_info.get('updatedAt', 'Just now')}\n"

                if applied_edits:
                    response += f"\nApplied {len(applied_edits)} edit(s):\n"
                    for old_text, new_text in applied_edits:
                        old_preview = (
                            old_text[:60] + "..." if len(old_text) > 60 else old_text
                        )
                        new_preview = (
                            new_text[:60] + "..." if len(new_text) > 60 else new_text
                        )
                        response += f'  - "{old_preview}" → "{new_preview}"\n'

                return response

        @self.app.tool(
            description="Permanently delete a wiki page by its numeric ID. This action cannot be undone."
        )
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

        @self.app.tool(
            description="Move a wiki page to a new path and/or locale. The page retains its numeric ID. Use this to reorganize the wiki hierarchy."
        )
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

                response = "✅ Successfully moved page:\n\n"
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

        @self.app.tool(
            description="List all tags used across wiki pages. Returns tag names and IDs. Use this to discover available tags before filtering wiki_list_pages by tag."
        )
        async def wiki_list_tags() -> str:
            """List all tags.

            Returns all tags used across the wiki with their IDs and timestamps.
            """
            async with WikiJSClient(self.config) as client:
                tags = await client.list_tags()

                if not tags:
                    return "No tags found"

                response = f"Found {len(tags)} tag(s):\n\n"
                for tag in tags:
                    response += f"**{tag.get('title', tag.get('tag', 'Unknown'))}**\n"
                    response += f"Tag: {tag.get('tag', '')}\n"
                    response += f"ID: {tag.get('id', '')}\n"
                    if tag.get("createdAt"):
                        response += f"Created: {tag['createdAt']}\n"
                    response += "\n"

                return response

        @self.app.tool(
            description="Get Wiki.js site metadata including title, description, and host URL. Useful for understanding which wiki instance you are connected to."
        )
        async def wiki_get_site_info() -> str:
            """Get site metadata.

            Returns the wiki's title, description, and host URL.
            """
            async with WikiJSClient(self.config) as client:
                config = await client.get_site_info()

                if not config:
                    return "Could not retrieve site information"

                response = "**Wiki Site Information:**\n\n"
                if config.get("title"):
                    response += f"**Title:** {config['title']}\n"
                if config.get("description"):
                    response += f"**Description:** {config['description']}\n"
                if config.get("host"):
                    response += f"**Host:** {config['host']}\n"

                return response

        @self.app.tool(
            description="Get the edit history of a wiki page. Returns a list of versions with timestamps, authors, and change types. Supports pagination via offset_page and offset_size."
        )
        async def wiki_get_history(
            page_id: int,
            offset_page: int = 0,
            offset_size: int = 100,
        ) -> str:
            """Get page edit history.

            Args:
                page_id: Page ID to get history for
                offset_page: Page offset for pagination (default: 0)
                offset_size: Number of entries per page (default: 100)
            """
            async with WikiJSClient(self.config) as client:
                history = await client.get_page_history(
                    page_id, offset_page, offset_size
                )

                trail = history.get("trail", [])
                total = history.get("total", 0)

                if not trail:
                    return f"No history found for page ID {page_id}"

                response = (
                    f"Page history for ID {page_id} ({total} total version(s)):\n\n"
                )
                for entry in trail:
                    response += f"**Version {entry.get('versionId', '?')}**\n"
                    response += f"Date: {entry.get('versionDate', 'Unknown')}\n"
                    response += f"Author: {entry.get('authorName', 'Unknown')}\n"
                    response += f"Action: {entry.get('actionType', 'Unknown')}\n"
                    response += "\n"

                return response

        @self.app.tool(
            description="Retrieve a specific historical version of a wiki page. Requires both the page ID and a version ID (obtained from wiki_get_history). Returns the full page content and metadata as they were at that point in time."
        )
        async def wiki_get_version(page_id: int, version_id: int) -> str:
            """Get a specific page version.

            Args:
                page_id: Page ID
                version_id: Version ID (from wiki_get_history)
            """
            async with WikiJSClient(self.config) as client:
                version = await client.get_page_version(page_id, version_id)

                if not version:
                    return "Version not found"

                response = f"# {version.get('title', 'Unknown')}\n\n"
                response += f"**Version ID:** {version.get('versionId', '?')}\n"
                response += (
                    f"**Version Date:** {version.get('versionDate', 'Unknown')}\n"
                )
                response += f"**Author:** {version.get('authorName', 'Unknown')}\n"
                response += f"**Action:** {version.get('action', 'Unknown')}\n"
                response += f"**Path:** {version.get('path', 'Unknown')}\n"
                response += f"**Editor:** {version.get('editor', 'Unknown')}\n"
                if version.get("contentType"):
                    response += f"**Content Type:** {version['contentType']}\n"
                if version.get("tags"):
                    response += f"**Tags:** {', '.join(version['tags'])}\n"
                response += "\n---\n\n"
                response += version.get("content", "")

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


async def _async_main():
    """Async entry point."""
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("WikiJS MCP Server")
        print("Usage:")
        print("  wikijs-mcp")
        print("  wikijs-mcp --help")
        print("")
        print("Runs the MCP server over stdio for use with Claude Code")
        print("and other MCP clients.")
        return

    server = WikiJSMCPServer()
    await server.run_stdio()


def main():
    """Entry point for the wikijs-mcp command."""
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
