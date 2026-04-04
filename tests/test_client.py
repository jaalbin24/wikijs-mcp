"""Tests for WikiJS GraphQL client."""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from wikijs_mcp.client import WikiJSClient
from wikijs_mcp.config import WikiJSConfig


@pytest.mark.unit
class TestWikiJSClient:
    """Test cases for WikiJSClient class."""

    def test_init(self, mock_wiki_config):
        """Test WikiJSClient initialization."""
        client = WikiJSClient(mock_wiki_config)

        assert client.config == mock_wiki_config
        assert isinstance(client.client, httpx.AsyncClient)

    async def test_context_manager(self, mock_wiki_config):
        """Test WikiJSClient as async context manager."""
        async with WikiJSClient(mock_wiki_config) as client:
            assert isinstance(client, WikiJSClient)

    async def test_execute_query_success(
        self, mock_wiki_config, sample_graphql_response
    ):
        """Test successful GraphQL query execution."""
        client = WikiJSClient(mock_wiki_config)

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = sample_graphql_response

        client.client.post = AsyncMock(return_value=mock_response)

        result = await client._execute_query("query { test }")

        assert result == sample_graphql_response["data"]
        client.client.post.assert_called_once()

    async def test_execute_query_with_variables(
        self, mock_wiki_config, sample_graphql_response
    ):
        """Test GraphQL query execution with variables."""
        client = WikiJSClient(mock_wiki_config)

        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = sample_graphql_response

        client.client.post = AsyncMock(return_value=mock_response)

        variables = {"query": "test", "limit": 10}
        await client._execute_query("query { test }", variables)

        # Verify the payload includes variables
        call_args = client.client.post.call_args
        payload = call_args[1]["json"]
        assert payload["variables"] == variables

    async def test_execute_query_graphql_errors(self, mock_wiki_config):
        """Test GraphQL query with GraphQL errors."""
        client = WikiJSClient(mock_wiki_config)

        error_response = {"errors": [{"message": "Invalid query"}], "data": None}

        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = error_response

        client.client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(Exception, match="GraphQL query failed"):
            await client._execute_query("invalid query")

    async def test_execute_query_http_error(self, mock_wiki_config):
        """Test GraphQL query with HTTP error."""
        client = WikiJSClient(mock_wiki_config)

        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        http_error = httpx.HTTPStatusError(
            "401 Unauthorized", request=Mock(), response=mock_response
        )

        client.client.post = AsyncMock(side_effect=http_error)

        with pytest.raises(Exception, match="API request failed: 401"):
            await client._execute_query("query { test }")

    async def test_search_pages_success(self, mock_wiki_config):
        """Test successful page search with new GraphQL schema."""
        client = WikiJSClient(mock_wiki_config)

        search_response = {
            "pages": {
                "search": {
                    "results": [
                        {
                            "id": "1",
                            "path": "docs/test",
                            "title": "Test Page",
                            "description": "Test description",
                            "locale": "en",
                        }
                    ],
                    "totalHits": 1,
                }
            }
        }

        client._execute_query = AsyncMock(return_value=search_response)

        results = await client.search_pages("test query", 5)

        assert len(results) == 1
        assert results[0]["title"] == "Test Page"
        assert results[0]["id"] == "1"
        assert results[0]["locale"] == "en"

        # Verify correct query and variables were used with new schema
        call_args = client._execute_query.call_args
        assert "SearchPages" in call_args[0][0]
        expected_vars = {"query": "test query", "path": "", "locale": "en"}
        assert call_args[0][1] == expected_vars

    async def test_search_pages_graphql_limit_applied(self, mock_wiki_config):
        """Test that limit is applied manually when GraphQL returns more results than requested."""
        client = WikiJSClient(mock_wiki_config)

        # Mock GraphQL to return more results than requested
        search_response = {
            "pages": {
                "search": {
                    "results": [
                        {
                            "id": str(i),
                            "path": f"docs/test{i}",
                            "title": f"Test Page {i}",
                            "description": "Test description",
                            "locale": "en",
                        }
                        for i in range(20)
                    ],
                    "totalHits": 20,
                }
            }
        }

        client._execute_query = AsyncMock(return_value=search_response)

        results = await client.search_pages("test query", 5)

        # Should return only 5 results due to manual limit application
        assert len(results) == 5
        for i, result in enumerate(results):
            assert result["title"] == f"Test Page {i}"

    async def test_search_pages_no_results(self, mock_wiki_config):
        """Test page search with no results."""
        client = WikiJSClient(mock_wiki_config)

        empty_response = {"pages": {"search": {"results": []}}}
        client._execute_query = AsyncMock(return_value=empty_response)

        results = await client.search_pages("nonexistent")

        assert results == []

    async def test_get_page_by_path_success(self, mock_wiki_config, sample_page_data):
        """Test successful get page by path with singleByPath query."""
        client = WikiJSClient(mock_wiki_config)

        # Update sample data to match new schema
        enhanced_page_data = {
            **sample_page_data,
            "isPublished": True,
            "isPrivate": False,
            "authorId": 1,
            "authorName": "Test Author",
            "authorEmail": "test@example.com",
            "creatorId": 1,
            "creatorName": "Test Creator",
            "creatorEmail": "creator@example.com",
            "tags": [
                {"id": 1, "tag": "test", "title": "Test Tag"},
                {"id": 2, "tag": "example", "title": "Example Tag"},
            ],
        }

        page_response = {"pages": {"singleByPath": enhanced_page_data}}
        client._execute_query = AsyncMock(return_value=page_response)

        result = await client.get_page_by_path("docs/test-page")

        assert result == enhanced_page_data
        assert result["title"] == "Test Page"
        assert result["isPublished"] is True
        assert result["authorName"] == "Test Author"

        # Verify correct query was used with new schema
        call_args = client._execute_query.call_args
        assert "GetPageByPath" in call_args[0][0]
        assert "singleByPath" in call_args[0][0]
        assert call_args[0][1] == {"path": "docs/test-page", "locale": "en"}

    async def test_get_page_by_path_with_custom_locale(
        self, mock_wiki_config, sample_page_data
    ):
        """Test get page by path with custom locale."""
        client = WikiJSClient(mock_wiki_config)

        page_response = {"pages": {"singleByPath": sample_page_data}}
        client._execute_query = AsyncMock(return_value=page_response)

        result = await client.get_page_by_path("docs/test-page", locale="fr")

        assert result == sample_page_data

        # Verify correct locale was passed
        call_args = client._execute_query.call_args
        assert call_args[0][1] == {"path": "docs/test-page", "locale": "fr"}

    async def test_get_page_by_path_not_found(self, mock_wiki_config):
        """Test get page by path when page not found."""
        client = WikiJSClient(mock_wiki_config)

        not_found_response = {"pages": {"singleByPath": None}}
        client._execute_query = AsyncMock(return_value=not_found_response)

        result = await client.get_page_by_path("nonexistent")

        assert result is None

    async def test_get_page_by_id_success(self, mock_wiki_config, sample_page_data):
        """Test successful get page by ID."""
        client = WikiJSClient(mock_wiki_config)

        page_response = {"pages": {"single": sample_page_data}}
        client._execute_query = AsyncMock(return_value=page_response)

        result = await client.get_page_by_id(123)

        assert result == sample_page_data

        # Verify correct query was used
        call_args = client._execute_query.call_args
        assert "GetPageById" in call_args[0][0]
        assert call_args[0][1] == {"id": 123}

    async def test_list_pages_success(self, mock_wiki_config):
        """Test successful list pages."""
        client = WikiJSClient(mock_wiki_config)

        pages_response = {
            "pages": {
                "list": [
                    {
                        "id": 1,
                        "path": "docs/page1",
                        "title": "Page 1",
                        "description": "First page",
                        "updatedAt": "2024-01-01T00:00:00Z",
                        "createdAt": "2024-01-01T00:00:00Z",
                        "locale": "en",
                    }
                ]
            }
        }

        client._execute_query = AsyncMock(return_value=pages_response)

        result = await client.list_pages(25)

        assert len(result) == 1
        assert result[0]["title"] == "Page 1"

        # Verify correct parameters
        call_args = client._execute_query.call_args
        assert call_args[0][1] == {"limit": 25}

    async def test_get_page_tree_success(self, mock_wiki_config):
        """Test successful get page tree with new schema."""
        client = WikiJSClient(mock_wiki_config)

        tree_response = {
            "pages": {
                "tree": [
                    {
                        "id": 1,
                        "path": "docs",
                        "depth": 0,
                        "title": "Documentation",
                        "isPrivate": False,
                        "isFolder": True,
                        "privateNS": None,
                        "parent": None,
                        "pageId": None,
                        "locale": "en",
                    }
                ]
            }
        }

        client._execute_query = AsyncMock(return_value=tree_response)

        result = await client.get_page_tree("docs", "ALL")

        assert len(result) == 1
        assert result[0]["isFolder"] is True
        assert result[0]["depth"] == 0
        assert result[0]["isPrivate"] is False

        # Verify correct parameters with new schema
        call_args = client._execute_query.call_args
        expected_vars = {
            "path": "docs",
            "parent": None,
            "mode": "ALL",
            "locale": "en",
            "includeAncestors": False,
        }
        assert call_args[0][1] == expected_vars

    async def test_get_page_tree_with_all_parameters(self, mock_wiki_config):
        """Test get page tree with all parameters specified."""
        client = WikiJSClient(mock_wiki_config)

        tree_response = {"pages": {"tree": []}}
        client._execute_query = AsyncMock(return_value=tree_response)

        result = await client.get_page_tree(
            parent_path="docs/advanced", mode="FOLDERS", locale="fr", parent_id=123
        )

        assert result == []

        # Verify all parameters were passed correctly
        call_args = client._execute_query.call_args
        expected_vars = {
            "path": "docs/advanced",
            "parent": 123,
            "mode": "FOLDERS",
            "locale": "fr",
            "includeAncestors": False,
        }
        assert call_args[0][1] == expected_vars

    async def test_get_page_tree_default_parameters(self, mock_wiki_config):
        """Test get page tree with default parameters."""
        client = WikiJSClient(mock_wiki_config)

        tree_response = {"pages": {"tree": []}}
        client._execute_query = AsyncMock(return_value=tree_response)

        result = await client.get_page_tree()

        assert result == []

        # Verify default parameters
        call_args = client._execute_query.call_args
        expected_vars = {
            "path": None,
            "parent": None,
            "mode": "ALL",
            "locale": "en",
            "includeAncestors": False,
        }
        assert call_args[0][1] == expected_vars

    async def test_create_page_success(self, mock_wiki_config):
        """Test successful page creation with new schema."""
        client = WikiJSClient(mock_wiki_config)

        create_response = {
            "pages": {
                "create": {
                    "responseResult": {
                        "succeeded": True,
                        "errorCode": None,
                        "slug": "new-page",
                        "message": "Page created successfully",
                    },
                    "page": {"id": 123, "path": "docs/new-page", "title": "New Page"},
                }
            }
        }

        client._execute_query = AsyncMock(return_value=create_response)

        result = await client.create_page(
            path="docs/new-page",
            title="New Page",
            content="# New Page\n\nContent here",
            description="A new page",
            tags=["test", "new"],
        )

        assert result["page"]["id"] == 123
        assert result["responseResult"]["succeeded"] is True

        # Verify correct parameters with new schema
        call_args = client._execute_query.call_args
        variables = call_args[0][1]
        expected_vars = {
            "content": "# New Page\n\nContent here",
            "description": "A new page",
            "editor": "markdown",
            "isPublished": True,
            "isPrivate": False,
            "locale": "en",
            "path": "docs/new-page",
            "tags": ["test", "new"],
            "title": "New Page",
        }
        assert variables == expected_vars

    async def test_create_page_with_custom_parameters(self, mock_wiki_config):
        """Test page creation with custom publication and privacy settings."""
        client = WikiJSClient(mock_wiki_config)

        create_response = {
            "pages": {
                "create": {
                    "responseResult": {
                        "succeeded": True,
                        "errorCode": None,
                        "slug": "private-page",
                        "message": "Page created successfully",
                    },
                    "page": {
                        "id": 124,
                        "path": "private/page",
                        "title": "Private Page",
                    },
                }
            }
        }

        client._execute_query = AsyncMock(return_value=create_response)

        result = await client.create_page(
            path="private/page",
            title="Private Page",
            content="# Private Content",
            description="A private page",
            editor="asciidoc",
            locale="fr",
            tags=["private", "draft"],
            is_published=False,
            is_private=True,
        )

        assert result["page"]["id"] == 124
        assert result["responseResult"]["succeeded"] is True

        # Verify custom parameters
        call_args = client._execute_query.call_args
        variables = call_args[0][1]
        assert variables["isPublished"] is False
        assert variables["isPrivate"] is True
        assert variables["editor"] == "asciidoc"
        assert variables["locale"] == "fr"

    async def test_create_page_failure(self, mock_wiki_config):
        """Test page creation failure."""
        client = WikiJSClient(mock_wiki_config)

        failed_response = {
            "pages": {
                "create": {
                    "responseResult": {
                        "succeeded": False,
                        "errorCode": "PAGE_CREATION_FAILED",
                        "message": "Page creation failed",
                    }
                }
            }
        }

        client._execute_query = AsyncMock(return_value=failed_response)

        with pytest.raises(Exception, match="Failed to create page"):
            await client.create_page("docs/fail", "Fail", "content")

    async def test_update_page_success(self, mock_wiki_config):
        """Test successful page update with enhanced parameter handling."""
        client = WikiJSClient(mock_wiki_config)

        # Mock get_page_by_id to return current page data
        current_page_data = {
            "id": 123,
            "path": "docs/current-page",
            "title": "Current Title",
            "content": "Current content",
            "description": "Current description",
            "editor": "markdown",
            "isPrivate": False,
            "isPublished": True,
            "locale": "en",
        }

        update_response = {
            "pages": {
                "update": {
                    "responseResult": {
                        "succeeded": True,
                        "errorCode": None,
                        "message": "Page updated successfully",
                    },
                    "page": {
                        "id": 123,
                        "path": "docs/updated-page",
                        "title": "Updated Page",
                        "updatedAt": "2024-01-01T12:00:00Z",
                    },
                }
            }
        }

        with patch.object(client, "get_page_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = current_page_data
            client._execute_query = AsyncMock(return_value=update_response)

            result = await client.update_page(
                page_id=123,
                content="# Updated Content",
                title="Updated Page",
                tags=["updated"],
            )

            assert result["page"]["id"] == 123
            assert result["responseResult"]["succeeded"] is True

            # Verify current page was fetched
            mock_get.assert_called_once_with(123)

            # Verify correct parameters with merged data
            call_args = client._execute_query.call_args
            variables = call_args[0][1]
            assert variables["id"] == 123
            assert variables["content"] == "# Updated Content"
            assert variables["title"] == "Updated Page"
            assert variables["tags"] == ["updated"]
            # Should preserve existing values
            assert variables["description"] == "Current description"
            assert variables["editor"] == "markdown"
            assert variables["isPrivate"] is False
            assert variables["path"] == "docs/current-page"

    async def test_update_page_partial_update(self, mock_wiki_config):
        """Test partial page update preserves existing values including tags."""
        client = WikiJSClient(mock_wiki_config)

        current_page_data = {
            "id": 456,
            "path": "docs/existing-page",
            "title": "Existing Title",
            "content": "Existing content",
            "description": "Existing description",
            "editor": "asciidoc",
            "isPrivate": True,
            "isPublished": False,
            "locale": "fr",
            "tags": [
                {"tag": "existing-tag", "title": "Existing Tag"},
                {"tag": "keep-me", "title": "Keep Me"},
            ],
        }

        update_response = {
            "pages": {
                "update": {
                    "responseResult": {
                        "succeeded": True,
                        "errorCode": None,
                        "message": "Page updated successfully",
                    },
                    "page": {"id": 456},
                }
            }
        }

        with patch.object(client, "get_page_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = current_page_data
            client._execute_query = AsyncMock(return_value=update_response)

            # Only update content and description — tags should be preserved
            result = await client.update_page(
                page_id=456, content="New content only", description="New description"
            )

            assert result["responseResult"]["succeeded"] is True

            call_args = client._execute_query.call_args
            variables = call_args[0][1]
            assert variables["content"] == "New content only"
            assert variables["description"] == "New description"
            assert variables["title"] == "Existing Title"
            assert variables["editor"] == "asciidoc"
            assert variables["isPrivate"] is True
            assert variables["isPublished"] is False
            assert variables["locale"] == "fr"
            assert variables["path"] == "docs/existing-page"
            assert variables["tags"] == ["existing-tag", "keep-me"]

    async def test_update_page_not_found(self, mock_wiki_config):
        """Test update page when page doesn't exist."""
        client = WikiJSClient(mock_wiki_config)

        with patch.object(client, "get_page_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            with pytest.raises(Exception, match="Page with ID 999 not found"):
                await client.update_page(page_id=999, content="New content")

    async def test_update_page_failure(self, mock_wiki_config):
        """Test page update failure when GraphQL returns error."""
        client = WikiJSClient(mock_wiki_config)

        # Mock get_page_by_id to return current page data first
        current_page_data = {
            "id": 123,
            "path": "docs/test-page",
            "title": "Test Title",
            "content": "Test content",
            "description": "Test description",
            "editor": "markdown",
            "isPrivate": False,
            "isPublished": True,
            "locale": "en",
        }

        failed_response = {
            "pages": {
                "update": {
                    "responseResult": {
                        "succeeded": False,
                        "errorCode": "PAGE_UPDATE_FAILED",
                        "message": "Page update failed",
                    }
                }
            }
        }

        with patch.object(client, "get_page_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = current_page_data
            client._execute_query = AsyncMock(return_value=failed_response)

            with pytest.raises(Exception, match="Failed to update page"):
                await client.update_page(123, "new content")

    async def test_delete_page_success(self, mock_wiki_config):
        """Test successful page deletion."""
        client = WikiJSClient(mock_wiki_config)

        delete_response = {
            "pages": {
                "delete": {
                    "responseResult": {
                        "succeeded": True,
                        "errorCode": None,
                        "message": "Page deleted successfully",
                    }
                }
            }
        }

        client._execute_query = AsyncMock(return_value=delete_response)

        result = await client.delete_page(123)

        assert result["responseResult"]["succeeded"] is True

        # Verify correct parameters
        call_args = client._execute_query.call_args
        assert call_args[0][1] == {"id": 123}

    async def test_delete_page_failure(self, mock_wiki_config):
        """Test page deletion failure."""
        client = WikiJSClient(mock_wiki_config)

        failed_response = {
            "pages": {
                "delete": {
                    "responseResult": {
                        "succeeded": False,
                        "errorCode": "PAGE_DELETE_FAILED",
                        "message": "Page deletion failed",
                    }
                }
            }
        }

        client._execute_query = AsyncMock(return_value=failed_response)

        with pytest.raises(Exception, match="Failed to delete page"):
            await client.delete_page(123)

    async def test_move_page_success(self, mock_wiki_config):
        """Test moving a page successfully."""
        client = WikiJSClient(mock_wiki_config)

        move_response = {
            "pages": {
                "move": {
                    "responseResult": {
                        "succeeded": True,
                        "errorCode": 0,
                        "message": "Page moved successfully",
                    }
                }
            }
        }

        client._execute_query = AsyncMock(return_value=move_response)

        result = await client.move_page(123, "docs/new-location", "fr")

        assert result == move_response["pages"]["move"]

        # Verify the GraphQL query was called correctly
        call_args = client._execute_query.call_args
        query = call_args[0][0]
        variables = call_args[0][1]

        assert "mutation MovePage" in query
        assert variables == {
            "id": 123,
            "destinationPath": "docs/new-location",
            "destinationLocale": "fr",
        }

    async def test_move_page_with_default_locale(self, mock_wiki_config):
        """Test moving a page with default locale."""
        client = WikiJSClient(mock_wiki_config)

        move_response = {
            "pages": {
                "move": {
                    "responseResult": {
                        "succeeded": True,
                        "errorCode": 0,
                        "message": None,
                    }
                }
            }
        }

        client._execute_query = AsyncMock(return_value=move_response)

        result = await client.move_page(456, "docs/moved-page")

        assert result == move_response["pages"]["move"]

        # Verify default locale is used
        call_args = client._execute_query.call_args
        variables = call_args[0][1]
        assert variables["destinationLocale"] == "en"

    async def test_move_page_failure(self, mock_wiki_config):
        """Test moving a page when the operation fails."""
        client = WikiJSClient(mock_wiki_config)

        failed_response = {
            "pages": {
                "move": {
                    "responseResult": {
                        "succeeded": False,
                        "errorCode": 404,
                        "message": "Page not found",
                    }
                }
            }
        }

        client._execute_query = AsyncMock(return_value=failed_response)

        with pytest.raises(Exception, match="Failed to move page: Page not found"):
            await client.move_page(999, "docs/nonexistent")

    @pytest.mark.parametrize(
        "method,args",
        [
            ("search_pages", ["test"]),
            ("get_page_by_path", ["docs/test"]),
            ("get_page_by_id", [123]),
            ("list_pages", []),
            ("get_page_tree", []),
        ],
    )
    async def test_methods_handle_missing_data(self, mock_wiki_config, method, args):
        """Test that methods handle missing data gracefully."""
        client = WikiJSClient(mock_wiki_config)

        # Empty response
        client._execute_query = AsyncMock(return_value={})

        result = await getattr(client, method)(*args)

        # Should return empty list or None without raising
        assert result in ([], None)
