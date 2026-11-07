"""Tests for configuration management."""

import os
from unittest.mock import patch

import pytest

from wikijs_mcp.config import (
    DEFAULT_MCP_ALLOWED_HOSTS,
    DEFAULT_MCP_ALLOWED_ORIGINS,
    WikiJSConfig,
    parse_mapping,
)


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
        assert config.read_only is False
        assert config.mcp_host == "127.0.0.1"
        assert config.mcp_port == 8000
        assert config.mcp_path == "/mcp"
        assert config.mcp_allowed_hosts == DEFAULT_MCP_ALLOWED_HOSTS
        assert config.mcp_allowed_origins == DEFAULT_MCP_ALLOWED_ORIGINS
        assert config.multi_user_auth_enabled is False

    def test_init_with_values(self):
        """Test WikiJSConfig initialization with specific values."""
        config = WikiJSConfig(
            url="https://test-wiki.com",
            api_key="test-key-123",
            graphql_endpoint="/api/graphql",
            debug=True,
            read_only=True,
            mcp_host="localhost",
            mcp_port=9000,
            mcp_path="/wiki-mcp",
            mcp_allowed_hosts=["127.0.0.1:*", "localhost:*", "mcp.example.com"],
            mcp_allowed_origins=[
                "http://127.0.0.1:*",
                "http://localhost:*",
                "https://mcp.example.com",
            ],
        )

        assert config.url == "https://test-wiki.com"
        assert config.api_key == "test-key-123"
        assert config.graphql_endpoint == "/api/graphql"
        assert config.debug is True
        assert config.read_only is True
        assert config.mcp_host == "localhost"
        assert config.mcp_port == 9000
        assert config.mcp_path == "/wiki-mcp"
        assert config.mcp_allowed_hosts == [
            "127.0.0.1:*",
            "localhost:*",
            "mcp.example.com",
        ]
        assert config.mcp_allowed_origins == [
            "http://127.0.0.1:*",
            "http://localhost:*",
            "https://mcp.example.com",
        ]

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
            "WIKIJS_READ_ONLY": "true",
            "MCP_HOST": "localhost",
            "MCP_PORT": "9000",
            "MCP_PATH": "/wiki-mcp",
            "MCP_ALLOWED_HOSTS": "127.0.0.1:*, localhost:*, mcp.example.com",
            "MCP_ALLOWED_ORIGINS": "http://127.0.0.1:*, http://localhost:*, https://mcp.example.com",
            "WIKIJS_CF_ACCESS_ISSUER": "https://team.cloudflareaccess.com",
            "WIKIJS_CF_ACCESS_AUDIENCE": "audience-tag",
            "WIKIJS_CF_ACCESS_JWKS_URL": "https://team.cloudflareaccess.com/cdn-cgi/access/certs",
            "WIKIJS_AUTH_USERS": "Admin@Example.com=admin,friend@example.com=friends",
            "WIKIJS_AUTH_PROFILES": "admin=WIKIJS_API_KEY_ADMIN,friends=WIKIJS_API_KEY_FRIENDS",
            "DEBUG": "true",
        }

        with patch.dict(os.environ, env_vars):
            config = WikiJSConfig.load_config()

        assert config.url == "https://test-wiki.com"
        assert config.api_key == "test-key-123"
        assert config.graphql_endpoint == "/api/graphql"
        assert config.debug is True
        assert config.read_only is True
        assert config.mcp_host == "localhost"
        assert config.mcp_port == 9000
        assert config.mcp_path == "/wiki-mcp"
        assert config.mcp_allowed_hosts == [
            "127.0.0.1:*",
            "localhost:*",
            "mcp.example.com",
        ]
        assert config.mcp_allowed_origins == [
            "http://127.0.0.1:*",
            "http://localhost:*",
            "https://mcp.example.com",
        ]
        assert config.cloudflare_access_issuer == "https://team.cloudflareaccess.com"
        assert config.cloudflare_access_audience == "audience-tag"
        assert config.cloudflare_access_jwks_url == (
            "https://team.cloudflareaccess.com/cdn-cgi/access/certs"
        )
        assert config.auth_users == {
            "admin@example.com": "admin",
            "friend@example.com": "friends",
        }
        assert config.auth_profiles == {
            "admin": "WIKIJS_API_KEY_ADMIN",
            "friends": "WIKIJS_API_KEY_FRIENDS",
        }
        assert config.multi_user_auth_enabled is True

    def test_parse_mapping_accepts_json(self):
        mapping = parse_mapping(
            '{"User@Example.com": "admin", "friend@example.com": "friends"}',
            normalize_keys=True,
        )

        assert mapping == {
            "user@example.com": "admin",
            "friend@example.com": "friends",
        }

    def test_validate_multi_user_auth_config_missing_values(self):
        config = WikiJSConfig(url="https://test.com", auth_users={"u@example.com": "p"})

        with pytest.raises(ValueError, match="WIKIJS_CF_ACCESS_ISSUER"):
            config.validate_multi_user_auth_config()

    def test_validate_multi_user_auth_config_undefined_profile(self):
        config = WikiJSConfig(
            url="https://test.com",
            cloudflare_access_issuer="https://team.cloudflareaccess.com",
            cloudflare_access_audience="aud",
            cloudflare_access_jwks_url="https://team.cloudflareaccess.com/certs",
            auth_users={"u@example.com": "missing"},
            auth_profiles={"admin": "WIKIJS_API_KEY_ADMIN"},
        )

        with pytest.raises(ValueError, match="undefined profile"):
            config.validate_multi_user_auth_config()

    def test_load_config_with_defaults(self):
        """Test that load_config uses defaults for missing env vars."""
        env_vars = {"WIKIJS_URL": "https://test.com", "WIKIJS_API_KEY": "test-key"}

        with patch.dict(os.environ, env_vars):
            config = WikiJSConfig.load_config()

        assert config.url == "https://test.com"
        assert config.api_key == "test-key"
        assert config.graphql_endpoint == "/graphql"
        assert config.debug is False
        assert config.read_only is False
        assert config.mcp_host == "127.0.0.1"
        assert config.mcp_port == 8000
        assert config.mcp_path == "/mcp"
        assert config.mcp_allowed_hosts == DEFAULT_MCP_ALLOWED_HOSTS
        assert config.mcp_allowed_origins == DEFAULT_MCP_ALLOWED_ORIGINS

    def test_allowed_hosts_empty_entries_are_ignored(self):
        """Test allowed host parsing ignores whitespace-only entries."""
        env_vars = {
            "MCP_ALLOWED_HOSTS": " 127.0.0.1:* , , localhost:* ,, mcp.example.com ",
        }

        with patch.dict(os.environ, env_vars):
            config = WikiJSConfig.load_config()

        assert config.mcp_allowed_hosts == [
            "127.0.0.1:*",
            "localhost:*",
            "mcp.example.com",
        ]

    def test_allowed_origins_empty_entries_are_ignored(self):
        """Test allowed origin parsing ignores whitespace-only entries."""
        env_vars = {
            "MCP_ALLOWED_ORIGINS": " http://127.0.0.1:* , , http://localhost:* ,, https://mcp.example.com ",
        }

        with patch.dict(os.environ, env_vars):
            config = WikiJSConfig.load_config()

        assert config.mcp_allowed_origins == [
            "http://127.0.0.1:*",
            "http://localhost:*",
            "https://mcp.example.com",
        ]

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

    @pytest.mark.parametrize(
        "read_only_value,expected",
        [
            ("true", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("0", False),
            ("no", False),
            ("", False),
            ("invalid", False),
        ],
    )
    def test_read_only_flag_parsing(self, read_only_value, expected):
        """Test read-only flag parsing from environment."""
        env_vars = {
            "WIKIJS_URL": "https://test.com",
            "WIKIJS_API_KEY": "test-key",
            "WIKIJS_READ_ONLY": read_only_value,
        }

        with patch.dict(os.environ, env_vars):
            config = WikiJSConfig.load_config()

        assert config.read_only is expected
