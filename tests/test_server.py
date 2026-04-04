"""Tests for MCP server functionality."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from wikijs_mcp.server import WikiJSMCPServer


def get_tool_response_text(result):
    """Helper function to extract text from MCP tool response.

    Handles both old format (list of TextContent) and new format (tuple with content and result dict).
    """
    if isinstance(result, tuple):
        content, _ = result
        return content[0].text
    else:
        return result[0].text


@pytest.mark.integration
class TestWikiJSMCPServer:
    """Test cases for WikiJSMCPServer class."""

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    def test_init(self, mock_load_config, mock_wiki_config):
        """Test WikiJSMCPServer initialization."""
        mock_load_config.return_value = mock_wiki_config

        server = WikiJSMCPServer()

        assert server.config == mock_wiki_config
        assert server.app is not None
        mock_load_config.assert_called_once()

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    async def test_list_tools(self, mock_load_config, mock_wiki_config):
        """Test MCP tools listing."""
        mock_load_config.return_value = mock_wiki_config
        server = WikiJSMCPServer()

        tools = await server.app.list_tools()
        assert len(tools) == 8  # 8 wiki tools

        tool_names = [tool.name for tool in tools]
        expected_names = [
            "wiki_search",
            "wiki_get_page",
            "wiki_list_pages",
            "wiki_get_tree",
            "wiki_create_page",
            "wiki_update_page",
            "wiki_delete_page",
            "wiki_move_page",
        ]
        assert set(tool_names) == set(expected_names)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_search_success(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling search tool with successful response."""
        # Setup mocks
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.search_pages.return_value = [
            {"title": "Test Page", "path": "/test", "updatedAt": "2023-01-01"}
        ]
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool(
            "wiki_search", {"query": "test", "limit": 10}
        )
        response_text = get_tool_response_text(result)
        assert "Found 1 pages for query 'test'" in response_text
        assert "Test Page" in response_text

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_search_no_results(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling search tool with no results."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.search_pages.return_value = []
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool(
            "wiki_search", {"query": "nonexistent", "limit": 10}
        )
        # MCP response format check removed
        assert "No pages found for query: nonexistent" in get_tool_response_text(result)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_search_with_new_response_format(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling search tool with new response format including locale and ID."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.search_pages.return_value = [
            {
                "id": "123",
                "title": "Test Page",
                "path": "/test",
                "description": "Test description",
                "locale": "en",
            }
        ]
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool(
            "wiki_search", {"query": "test", "limit": 10}
        )
        # MCP response format check removed
        assert "Test description" in get_tool_response_text(result)
        assert "Locale: en" in get_tool_response_text(result)
        assert "ID: 123" in get_tool_response_text(result)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_get_page_by_path(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling get_page tool with path."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.get_page_by_path.return_value = {
            "id": 1,
            "title": "Test Page",
            "path": "/test",
            "content": "Test content",
            "createdAt": "2023-01-01",
            "updatedAt": "2023-01-02",
        }
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool("wiki_get_page", {"path": "/test"})
        # MCP response format check removed
        assert "Test Page" in get_tool_response_text(result)
        assert "Test content" in get_tool_response_text(result)

        # Verify default locale was used
        mock_client_instance.get_page_by_path.assert_called_once_with("/test", "en")

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_get_page_by_path_with_locale(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling get_page tool with path and custom locale."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.get_page_by_path.return_value = {
            "id": 1,
            "title": "Page Française",
            "path": "/test-fr",
            "content": "Contenu français",
            "locale": "fr",
            "createdAt": "2023-01-01",
            "updatedAt": "2023-01-02",
        }
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool(
            "wiki_get_page", {"path": "/test-fr", "locale": "fr"}
        )
        # MCP response format check removed
        assert "Page Française" in get_tool_response_text(result)
        assert "Contenu français" in get_tool_response_text(result)

        # Verify custom locale was used
        mock_client_instance.get_page_by_path.assert_called_once_with("/test-fr", "fr")

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_get_page_by_id(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling get_page tool with ID."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.get_page_by_id.return_value = {
            "id": 1,
            "title": "Test Page",
            "path": "/test",
            "content": "Test content",
            "createdAt": "2023-01-01",
            "updatedAt": "2023-01-02",
        }
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool("wiki_get_page", {"id": 1})
        # MCP response format check removed
        assert "Test Page" in get_tool_response_text(result)
        assert "Test content" in get_tool_response_text(result)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_get_page_not_found(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling get_page tool with non-existent page."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.get_page_by_path.return_value = None
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool("wiki_get_page", {"path": "/nonexistent"})
        # MCP response format check removed
        assert "Page not found" in get_tool_response_text(result)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_get_page_validation_errors(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test get_page tool validation errors."""
        from mcp.server.fastmcp.exceptions import ToolError

        mock_load_config.return_value = mock_wiki_config
        server = WikiJSMCPServer()

        # Test no parameters
        with pytest.raises(
            ToolError, match="Either 'path' or 'id' parameter is required"
        ):
            await server.app.call_tool("wiki_get_page", {})

        # Test both parameters
        with pytest.raises(
            ToolError, match="Cannot specify both 'path' and 'id' parameters"
        ):
            await server.app.call_tool("wiki_get_page", {"path": "/test", "id": 1})

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_get_page_with_enhanced_metadata(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test get_page tool with enhanced metadata format."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.get_page_by_path.return_value = {
            "id": 1,
            "title": "Test Page",
            "path": "/test",
            "content": "Test content",
            "description": "Test description",
            "editor": "markdown",
            "locale": "en",
            "authorName": "Test Author",  # Updated from nested author object
            "tags": [
                {"tag": "test", "title": "Test Tag"},
                {"tag": "example", "title": "Example Tag"},
            ],
            "createdAt": "2023-01-01",
            "updatedAt": "2023-01-02",
        }
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool("wiki_get_page", {"path": "/test"})
        # MCP response format check removed
        assert "Test description" in get_tool_response_text(result)
        assert "Test Author" in get_tool_response_text(result)
        # Should handle both tag formats (tag and title)
        assert "test, example" in get_tool_response_text(result)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_list_pages(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling list_pages tool."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.list_pages.return_value = [
            {"id": 1, "title": "Test Page", "path": "/test", "updatedAt": "2023-01-01"}
        ]
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool("wiki_list_pages", {"limit": 50})
        # MCP response format check removed
        assert "Found 1 pages" in get_tool_response_text(result)
        assert "Test Page" in get_tool_response_text(result)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_list_pages_no_results(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling list_pages tool with no results."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.list_pages.return_value = []
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool("wiki_list_pages", {"limit": 50})
        # MCP response format check removed
        assert "No pages found" in get_tool_response_text(result)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_list_pages_with_description(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling list_pages tool with page description."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.list_pages.return_value = [
            {
                "id": 1,
                "title": "Test Page",
                "path": "/test",
                "description": "Test description",
                "updatedAt": "2023-01-01",
            }
        ]
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool("wiki_list_pages", {"limit": 50})
        # MCP response format check removed
        assert "Test description" in get_tool_response_text(result)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_get_tree(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling get_tree tool with enhanced parameters."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.get_page_tree.return_value = [
            {"title": "Folder", "isFolder": True, "depth": 0},
            {"title": "Page", "path": "/page", "isFolder": False, "depth": 1},
        ]
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool("wiki_get_tree", {"parent_path": ""})
        # MCP response format check removed
        assert "📁 Folder/" in get_tool_response_text(result)
        assert "📄 Page" in get_tool_response_text(result)

        # Verify default parameters were used
        mock_client_instance.get_page_tree.assert_called_once_with(
            "", "ALL", "en", None
        )

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_get_tree_with_all_parameters(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling get_tree tool with all parameters."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.get_page_tree.return_value = [
            {"title": "Advanced Folder", "isFolder": True, "depth": 0},
        ]
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool(
            "wiki_get_tree",
            {
                "parent_path": "docs/advanced",
                "mode": "FOLDERS",
                "locale": "fr",
                "parent_id": 123,
            },
        )
        # MCP response format check removed
        assert "Advanced Folder" in get_tool_response_text(result)
        assert "(mode: FOLDERS)" in get_tool_response_text(result)

        # Verify all parameters were passed correctly
        mock_client_instance.get_page_tree.assert_called_once_with(
            "docs/advanced", "FOLDERS", "fr", 123
        )

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_get_tree_no_results(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling get_tree tool with no results."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.get_page_tree.return_value = []
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool("wiki_get_tree", {"parent_path": ""})
        # MCP response format check removed
        assert "No pages found in tree" in get_tool_response_text(result)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_create_page(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling create_page tool."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.create_page.return_value = {
            "page": {"id": 1, "title": "New Page", "path": "/new"}
        }
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool(
            "wiki_create_page",
            {"path": "/new", "title": "New Page", "content": "New content"},
        )
        # MCP response format check removed
        assert "Successfully created page" in get_tool_response_text(result)
        assert "New Page" in get_tool_response_text(result)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_create_page_with_tags(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling create_page tool with tags."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.create_page.return_value = {
            "page": {"id": 1, "title": "New Page", "path": "/new"}
        }
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool(
            "wiki_create_page",
            {
                "path": "/new",
                "title": "New Page",
                "content": "New content",
                "description": "Test description",
                "tags": ["test", "example"],
            },
        )
        # MCP response format check removed
        assert "Successfully created page" in get_tool_response_text(result)
        mock_client_instance.create_page.assert_called_once_with(
            path="/new",
            title="New Page",
            content="New content",
            description="Test description",
            tags=["test", "example"],
        )

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_update_page(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling update_page tool."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.update_page.return_value = {
            "page": {
                "id": 1,
                "title": "Updated Page",
                "path": "/updated",
                "updatedAt": "2023-01-02",
            }
        }
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool(
            "wiki_update_page", {"id": 1, "content": "Updated content"}
        )
        # MCP response format check removed
        assert "Successfully updated page" in get_tool_response_text(result)
        assert "Updated Page" in get_tool_response_text(result)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_update_page_with_metadata(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling update_page tool with metadata."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.update_page.return_value = {
            "page": {
                "id": 1,
                "title": "Updated Page",
                "path": "/updated",
                "updatedAt": "2023-01-02",
            }
        }
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool(
            "wiki_update_page",
            {
                "id": 1,
                "content": "Updated content",
                "title": "New Title",
                "description": "New description",
                "tags": ["updated"],
            },
        )
        # MCP response format check removed
        assert "Successfully updated page" in get_tool_response_text(result)
        mock_client_instance.update_page.assert_called_once_with(
            page_id=1,
            content="Updated content",
            title="New Title",
            description="New description",
            tags=["updated"],
        )

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_update_page_with_edits(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling update_page tool with find-and-replace edits."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.get_page_by_id.return_value = {
            "id": 1,
            "title": "Test Page",
            "path": "/test",
            "content": "Hello world. This is old text. Goodbye.",
        }
        mock_client_instance.update_page.return_value = {
            "page": {
                "id": 1,
                "title": "Test Page",
                "path": "/test",
                "updatedAt": "2023-01-02",
            }
        }
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool(
            "wiki_update_page",
            {
                "id": 1,
                "edits": [
                    {"old_text": "old text", "new_text": "new text"},
                    {"old_text": "Goodbye", "new_text": "Farewell"},
                ],
            },
        )
        response_text = get_tool_response_text(result)
        assert "Successfully updated page" in response_text
        assert "Applied 2 edit(s)" in response_text
        assert '"old text" → "new text"' in response_text

        # Verify the final content passed to update_page
        call_args = mock_client_instance.update_page.call_args
        assert call_args[1]["content"] == "Hello world. This is new text. Farewell."

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_update_page_edits_not_found(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test update_page with edits when old_text is not found."""
        from mcp.server.fastmcp.exceptions import ToolError

        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.get_page_by_id.return_value = {
            "id": 1,
            "title": "Test Page",
            "path": "/test",
            "content": "Hello world.",
        }
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        with pytest.raises(ToolError, match="old_text not found in page content"):
            await server.app.call_tool(
                "wiki_update_page",
                {
                    "id": 1,
                    "edits": [{"old_text": "nonexistent text", "new_text": "new"}],
                },
            )

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_update_page_content_and_edits_conflict(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test update_page rejects both content and edits."""
        from mcp.server.fastmcp.exceptions import ToolError

        mock_load_config.return_value = mock_wiki_config
        server = WikiJSMCPServer()

        with pytest.raises(
            ToolError, match="Cannot specify both 'content' and 'edits'"
        ):
            await server.app.call_tool(
                "wiki_update_page",
                {
                    "id": 1,
                    "content": "full content",
                    "edits": [{"old_text": "a", "new_text": "b"}],
                },
            )

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_delete_page_success(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling delete_page tool successfully."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.delete_page.return_value = {
            "responseResult": {
                "succeeded": True,
                "errorCode": None,
                "message": "Page deleted successfully",
            }
        }
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool("wiki_delete_page", {"id": 123})
        # MCP response format check removed
        assert "Successfully deleted page with ID: 123" in get_tool_response_text(
            result
        )
        assert "Page deleted successfully" in get_tool_response_text(result)

        # Verify client method was called correctly
        mock_client_instance.delete_page.assert_called_once_with(page_id=123)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_delete_page_without_message(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling delete_page tool without message in response."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None
        mock_client_instance.delete_page.return_value = {
            "responseResult": {"succeeded": True, "errorCode": None}
        }
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool("wiki_delete_page", {"id": 456})
        # MCP response format check removed
        assert "Successfully deleted page with ID: 456" in get_tool_response_text(
            result
        )
        # Should not have a message line since no message in response
        assert "Message:" not in get_tool_response_text(result)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_delete_page_failure(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling delete_page tool when deletion fails."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None

        # Mock the client to raise an exception (this is what happens in client when deletion fails)
        mock_client_instance.delete_page.side_effect = Exception(
            "Failed to delete page: Page not found"
        )
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        # The server should propagate the exception from the client
        with pytest.raises(Exception, match="Failed to delete page: Page not found"):
            await server.app.call_tool("wiki_delete_page", {"id": 999})

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_move_page_success(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling move_page tool successfully."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None

        # Mock getting current page info
        mock_client_instance.get_page_by_id.return_value = {
            "id": 123,
            "title": "Test Page",
            "path": "docs/test-page",
            "locale": "en",
        }

        # Mock move operation
        mock_client_instance.move_page.return_value = {
            "responseResult": {
                "succeeded": True,
                "errorCode": None,
                "message": "Page moved successfully",
            }
        }
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool(
            "wiki_move_page",
            {
                "id": 123,
                "destination_path": "docs/moved-page",
                "destination_locale": "fr",
            },
        )

        # MCP response format check removed
        response_text = get_tool_response_text(result)
        assert "Successfully moved page" in response_text
        assert "Test Page" in response_text
        assert "docs/test-page" in response_text
        assert "docs/moved-page" in response_text
        assert "locale: en" in response_text
        assert "locale: fr" in response_text
        assert "Page moved successfully" in response_text

        # Verify client methods were called correctly
        mock_client_instance.get_page_by_id.assert_called_once_with(123)
        mock_client_instance.move_page.assert_called_once_with(
            page_id=123, destination_path="docs/moved-page", destination_locale="fr"
        )

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_move_page_with_default_locale(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling move_page tool with default locale."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None

        # Mock getting current page info
        mock_client_instance.get_page_by_id.return_value = {
            "id": 456,
            "title": "Another Page",
            "path": "old/location",
            "locale": "en",
        }

        # Mock move operation
        mock_client_instance.move_page.return_value = {
            "responseResult": {"succeeded": True, "errorCode": None}
        }
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool(
            "wiki_move_page", {"id": 456, "destination_path": "new/location"}
        )

        # MCP response format check removed
        response_text = get_tool_response_text(result)
        assert "Successfully moved page" in response_text
        assert "Another Page" in response_text

        # Verify default locale was used
        mock_client_instance.move_page.assert_called_once_with(
            page_id=456, destination_path="new/location", destination_locale="en"
        )

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_move_page_not_found(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling move_page tool when page doesn't exist."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None

        # Mock page not found
        mock_client_instance.get_page_by_id.return_value = None
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        result = await server.app.call_tool(
            "wiki_move_page", {"id": 999, "destination_path": "new/location"}
        )

        # MCP response format check removed
        assert "Page with ID 999 not found" in get_tool_response_text(result)

        # Move should not be called since page wasn't found
        mock_client_instance.move_page.assert_not_called()

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient")
    async def test_call_tool_move_page_failure(
        self, mock_client_class, mock_load_config, mock_wiki_config
    ):
        """Test calling move_page tool when move operation fails."""
        mock_load_config.return_value = mock_wiki_config
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None

        # Mock getting current page info
        mock_client_instance.get_page_by_id.return_value = {
            "id": 123,
            "title": "Test Page",
            "path": "docs/test-page",
            "locale": "en",
        }

        # Mock the client to raise an exception (this is what happens in client when move fails)
        mock_client_instance.move_page.side_effect = Exception(
            "Failed to move page: Destination already exists"
        )
        mock_client_class.return_value = mock_client_instance

        server = WikiJSMCPServer()

        # The server should propagate the exception from the client
        with pytest.raises(
            Exception, match="Failed to move page: Destination already exists"
        ):
            await server.app.call_tool(
                "wiki_move_page", {"id": 123, "destination_path": "docs/existing-page"}
            )

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.config.WikiJSConfig.validate_config")
    async def test_run_stdio(self, mock_validate, mock_load_config, mock_wiki_config):
        """Test run_stdio method."""
        mock_load_config.return_value = mock_wiki_config

        server = WikiJSMCPServer()

        with patch.object(server.app, "run_stdio_async") as mock_run:
            await server.run_stdio()
            mock_run.assert_called_once()
            mock_validate.assert_called_once()

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.config.WikiJSConfig.validate_config")
    async def test_run_stdio_validation_error(
        self, mock_validate, mock_load_config, mock_wiki_config
    ):
        """Test run_stdio method with validation error."""
        mock_load_config.return_value = mock_wiki_config
        mock_validate.side_effect = ValueError("Invalid config")

        server = WikiJSMCPServer()

        with pytest.raises(ValueError, match="Invalid config"):
            await server.run_stdio()


@pytest.mark.integration
class TestMainFunction:
    """Test cases for main function."""

    @patch("wikijs_mcp.server.WikiJSMCPServer")
    @patch("logging.basicConfig")
    @patch("sys.argv", ["wikijs-mcp"])
    async def test_main_runs_stdio(self, mock_logging, mock_server_class):
        """Test main function runs stdio server."""
        from wikijs_mcp.server import _async_main

        mock_server = AsyncMock()
        mock_server_class.return_value = mock_server

        await _async_main()

        mock_server.run_stdio.assert_called_once()

    @patch("sys.argv", ["wikijs-mcp", "--help"])
    @patch("builtins.print")
    async def test_main_help_arg(self, mock_print):
        """Test main function with --help argument."""
        from wikijs_mcp.server import _async_main

        await _async_main()

        mock_print.assert_called()
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        assert any("WikiJS MCP Server" in call for call in print_calls)
        assert any("Usage:" in call for call in print_calls)
