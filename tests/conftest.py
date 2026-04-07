"""Pytest configuration and fixtures."""

import os
from unittest.mock import Mock, patch

import pytest

from wikijs_mcp.config import WikiJSConfig


@pytest.fixture
def mock_wiki_config():
    """Mock WikiJS configuration."""
    return WikiJSConfig(
        url="https://test-wiki.example.com",
        api_key="test-api-key-123",
        graphql_endpoint="/graphql",
        debug=True,
    )


@pytest.fixture
def mock_httpx_client():
    """Mock httpx.AsyncClient for API testing."""
    with patch("httpx.AsyncClient") as mock_client:
        mock_instance = Mock()
        mock_client.return_value = mock_instance

        mock_instance.__aenter__ = Mock(return_value=mock_instance)
        mock_instance.__aexit__ = Mock(return_value=None)

        yield mock_instance


@pytest.fixture
def sample_graphql_response():
    """Sample GraphQL API response."""
    return {
        "data": {
            "pages": {
                "search": {
                    "results": [
                        {
                            "id": 1,
                            "path": "docs/getting-started",
                            "title": "Getting Started",
                            "description": "A guide to get started",
                            "updatedAt": "2024-01-01T00:00:00Z",
                            "createdAt": "2024-01-01T00:00:00Z",
                        }
                    ]
                }
            }
        }
    }


@pytest.fixture
def sample_page_data():
    """Sample page data for testing."""
    return {
        "id": 1,
        "path": "docs/test-page",
        "title": "Test Page",
        "description": "A test page",
        "content": "# Test Page\n\nThis is test content.",
        "contentType": "markdown",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
        "author": {"name": "Test User", "email": "test@example.com"},
        "editor": "markdown",
        "locale": "en",
        "tags": [{"tag": "test"}, {"tag": "documentation"}],
    }


@pytest.fixture
def sample_history_data():
    """Sample page history data for testing."""
    return {
        "trail": [
            {
                "versionId": 1,
                "versionDate": "2024-01-01T00:00:00Z",
                "authorId": 1,
                "authorName": "Test User",
                "actionType": "updated",
                "valueBefore": "",
                "valueAfter": "",
            }
        ],
        "total": 1,
    }


@pytest.fixture
def sample_version_data():
    """Sample page version data for testing."""
    return {
        "action": "updated",
        "authorId": "1",
        "authorName": "Test User",
        "content": "# Version Content",
        "contentType": "markdown",
        "createdAt": "2024-01-01T00:00:00Z",
        "versionDate": "2024-01-01T00:00:00Z",
        "description": "Test version",
        "editor": "markdown",
        "isPrivate": False,
        "isPublished": True,
        "locale": "en",
        "path": "docs/test-page",
        "tags": ["test"],
        "title": "Test Page Version",
        "versionId": 1,
    }


@pytest.fixture
def sample_tags_data():
    """Sample tags data for testing."""
    return [
        {
            "id": 1,
            "tag": "dev",
            "title": "Development",
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-01-01T00:00:00Z",
        },
        {
            "id": 2,
            "tag": "docs",
            "title": "Documentation",
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-01-01T00:00:00Z",
        },
    ]


@pytest.fixture
def sample_site_config():
    """Sample site configuration data for testing."""
    return {
        "title": "Test Wiki",
        "description": "A test wiki instance",
        "host": "https://wiki.example.com",
    }


@pytest.fixture(autouse=True)
def clean_env():
    """Clean environment variables before each test."""
    env_vars = ["WIKIJS_URL", "WIKIJS_API_KEY", "WIKIJS_GRAPHQL_ENDPOINT", "DEBUG"]

    original_values = {}
    for var in env_vars:
        original_values[var] = os.environ.get(var)
        if var in os.environ:
            del os.environ[var]

    yield

    for var, value in original_values.items():
        if value is not None:
            os.environ[var] = value
        elif var in os.environ:
            del os.environ[var]
