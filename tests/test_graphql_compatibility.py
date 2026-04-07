"""Tests for GraphQL API compatibility with Wiki.js."""

from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from wikijs_mcp.client import WikiJSClient
from wikijs_mcp.config import WikiJSConfig


@pytest.mark.unit
class TestGraphQLCompatibility:
    """Test cases for ensuring GraphQL queries are compatible with Wiki.js API."""

    async def test_list_pages_no_offset_parameter(self, mock_wiki_config):
        """Test that list_pages doesn't send offset parameter to API."""
        client = WikiJSClient(mock_wiki_config)

        # Mock successful response
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "data": {"pages": {"list": [{"id": 1, "title": "Test", "path": "/test"}]}}
        }

        client.client.post = AsyncMock(return_value=mock_response)

        # Call list_pages with limit only
        await client.list_pages(limit=10)

        # Verify the GraphQL query
        call_args = client.client.post.call_args
        payload = call_args[1]["json"]

        # Check that query doesn't contain offset
        assert "offset" not in payload["query"]
        assert "offset" not in payload.get("variables", {})

        # Verify limit and ordering are sent but no offset
        assert payload["variables"]["limit"] == 10
        assert "offset" not in str(payload["variables"]).lower()

    async def test_list_pages_query_structure(self, mock_wiki_config):
        """Test the exact GraphQL query structure for list_pages."""
        client = WikiJSClient(mock_wiki_config)

        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"data": {"pages": {"list": []}}}

        client.client.post = AsyncMock(return_value=mock_response)

        await client.list_pages(limit=5)

        # Get the actual query sent
        call_args = client.client.post.call_args
        query = call_args[1]["json"]["query"]

        # Verify query structure
        assert "query ListPages(" in query
        assert "$limit: Int!" in query
        assert "list(" in query
        assert "limit: $limit" in query
        assert "author" not in query  # No author field
        assert "offset" not in query  # No offset parameter

    async def test_list_pages_response_without_author(self, mock_wiki_config):
        """Test that list_pages handles responses without author field."""
        client = WikiJSClient(mock_wiki_config)

        # Response without author field (as Wiki.js actually returns)
        pages_response = {
            "pages": {
                "list": [
                    {
                        "id": 1,
                        "path": "home",
                        "title": "Home",
                        "description": "Homepage",
                        "updatedAt": "2024-01-01T00:00:00Z",
                        "createdAt": "2024-01-01T00:00:00Z",
                        "locale": "en",
                        # Note: no author field
                    }
                ]
            }
        }

        client._execute_query = AsyncMock(return_value=pages_response)

        result = await client.list_pages()

        assert len(result) == 1
        assert result[0]["title"] == "Home"
        assert "author" not in result[0]  # Should not have author field

    async def test_handle_wikijs_graphql_errors(self, mock_wiki_config):
        """Test handling of Wiki.js specific GraphQL errors."""
        client = WikiJSClient(mock_wiki_config)

        # Simulate the exact error we got from Wiki.js
        error_response = Mock()
        error_response.raise_for_status.return_value = None
        error_response.status_code = 400
        error_response.text = '{"errors":[{"message":"Unknown argument \\"offset\\" on field \\"PageQuery.list\\"."}]}'
        error_response.json.return_value = {
            "errors": [
                {
                    "message": 'Unknown argument "offset" on field "PageQuery.list".',
                    "locations": [{"line": 4, "column": 37}],
                    "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"},
                }
            ]
        }

        # Create HTTPStatusError
        http_error = httpx.HTTPStatusError(
            "400 Bad Request", request=Mock(), response=error_response
        )

        client.client.post = AsyncMock(side_effect=http_error)

        with pytest.raises(Exception, match="API request failed: 400"):
            await client._execute_query("invalid query", {"offset": 0})

    async def test_search_pages_query_compatibility(self, mock_wiki_config):
        """Test search_pages query is compatible with Wiki.js."""
        client = WikiJSClient(mock_wiki_config)

        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "data": {"pages": {"search": {"results": []}}}
        }

        client.client.post = AsyncMock(return_value=mock_response)

        await client.search_pages("test", limit=10)

        # Verify the query structure (updated to match new implementation)
        call_args = client.client.post.call_args
        query = call_args[1]["json"]["query"]

        assert (
            "query SearchPages($query: String!, $path: String, $locale: String)"
            in query
        )
        assert "search(query: $query, path: $path, locale: $locale)" in query

    async def test_get_page_tree_compatibility(self, mock_wiki_config):
        """Test get_page_tree with correct GraphQL schema."""
        client = WikiJSClient(mock_wiki_config)

        # Mock tree response matching the actual schema
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "data": {
                "pages": {
                    "tree": [
                        {
                            "id": 1,
                            "path": "docs",
                            "depth": 0,
                            "title": "Documentation",
                            "isPrivate": False,
                            "isFolder": True,
                            "parent": None,
                            "pageId": None,
                            "locale": "en",
                        }
                    ]
                }
            }
        }

        client.client.post = AsyncMock(return_value=mock_response)

        result = await client.get_page_tree()

        # Verify tree structure
        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["path"] == "docs"
        assert result[0]["title"] == "Documentation"
        assert result[0]["isFolder"]

    @pytest.mark.parametrize(
        "field_list,should_contain,should_not_contain",
        [
            # Test list_pages fields
            (
                [
                    "id",
                    "path",
                    "title",
                    "description",
                    "updatedAt",
                    "createdAt",
                    "locale",
                ],
                ["id", "path", "title"],  # Must have these
                ["author", "offset"],  # Must not have these
            ),
        ],
    )
    async def test_query_field_compatibility(
        self, mock_wiki_config, field_list, should_contain, should_not_contain
    ):
        """Test that GraphQL queries only request fields that exist in Wiki.js schema."""
        client = WikiJSClient(mock_wiki_config)

        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"data": {"pages": {"list": []}}}

        client.client.post = AsyncMock(return_value=mock_response)

        await client.list_pages()

        call_args = client.client.post.call_args
        query = call_args[1]["json"]["query"]

        # Check required fields are present
        for field in should_contain:
            assert field in query

        # Check forbidden fields are not present
        for field in should_not_contain:
            assert field not in query
