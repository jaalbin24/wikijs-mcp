"""Tests for configuration management."""

import os
from unittest.mock import patch

import pytest

from wikijs_mcp.config import WikiJSConfig


@pytest.mark.unit
class TestWikiJSConfig:
    """Test cases for WikiJSConfig class."""

    def test_init_with_defaults(self):
        """Test WikiJSConfig initialization with defaults."""
        config = WikiJSConfig()

        assert config.url == ""
        assert config.api_key == ""
        assert config.graphql_endpoint == "/graphql"
        assert config.debug is False

    def test_init_with_values(self):
        """Test WikiJSConfig initialization with specific values."""
        config = WikiJSConfig(
            url="https://test-wiki.com",
            api_key="test-key-123",
            graphql_endpoint="/api/graphql",
            debug=True,
        )

        assert config.url == "https://test-wiki.com"
        assert config.api_key == "test-key-123"
        assert config.graphql_endpoint == "/api/graphql"
        assert config.debug is True

    def test_graphql_url_property(self):
        """Test graphql_url property construction."""
        config = WikiJSConfig(url="https://test-wiki.com", graphql_endpoint="/graphql")

        assert config.graphql_url == "https://test-wiki.com/graphql"

    def test_graphql_url_property_trailing_slash(self):
        """Test graphql_url property with trailing slash in URL."""
        config = WikiJSConfig(url="https://test-wiki.com/", graphql_endpoint="/graphql")

        assert config.graphql_url == "https://test-wiki.com/graphql"

    def test_headers_property(self):
        """Test headers property construction."""
        config = WikiJSConfig(api_key="test-api-key-123")

        headers = config.headers

        assert headers["Authorization"] == "Bearer test-api-key-123"
        assert headers["Content-Type"] == "application/json"

    def test_validate_config_success(self):
        """Test successful config validation."""
        config = WikiJSConfig(url="https://test-wiki.com", api_key="test-api-key")

        config.validate_config()

    def test_validate_config_missing_url(self):
        """Test config validation with missing URL."""
        config = WikiJSConfig(api_key="test-api-key")

        with pytest.raises(ValueError, match="WIKIJS_URL"):
            config.validate_config()

    def test_validate_config_missing_api_key(self):
        """Test config validation with missing API key."""
        config = WikiJSConfig(url="https://test-wiki.com")

        with pytest.raises(ValueError, match="WIKIJS_API_KEY"):
            config.validate_config()

    def test_validate_config_missing_both(self):
        """Test config validation with missing URL and API key."""
        config = WikiJSConfig()

        with pytest.raises(ValueError, match="WIKIJS_URL"):
            config.validate_config()

    def test_load_config_from_env_vars(self):
        """Test loading config from environment variables."""
        env_vars = {
            "WIKIJS_URL": "https://test-wiki.com",
            "WIKIJS_API_KEY": "test-key-123",
            "WIKIJS_GRAPHQL_ENDPOINT": "/api/graphql",
            "DEBUG": "true",
        }

        with patch.dict(os.environ, env_vars):
            config = WikiJSConfig.load_config()

        assert config.url == "https://test-wiki.com"
        assert config.api_key == "test-key-123"
        assert config.graphql_endpoint == "/api/graphql"
        assert config.debug is True

    def test_load_config_with_defaults(self):
        """Test that load_config uses defaults for missing env vars."""
        env_vars = {"WIKIJS_URL": "https://test.com", "WIKIJS_API_KEY": "test-key"}

        with patch.dict(os.environ, env_vars):
            config = WikiJSConfig.load_config()

        assert config.url == "https://test.com"
        assert config.api_key == "test-key"
        assert config.graphql_endpoint == "/graphql"
        assert config.debug is False

    @pytest.mark.parametrize(
        "debug_value,expected",
        [
            ("true", True),
            ("TRUE", True),
            ("True", True),
            ("false", False),
            ("FALSE", False),
            ("False", False),
            ("", False),
            ("invalid", False),
        ],
    )
    def test_debug_flag_parsing(self, debug_value, expected):
        """Test debug flag parsing from environment."""
        env_vars = {
            "WIKIJS_URL": "https://test.com",
            "WIKIJS_API_KEY": "test-key",
            "DEBUG": debug_value,
        }

        with patch.dict(os.environ, env_vars):
            config = WikiJSConfig.load_config()

        assert config.debug is expected
