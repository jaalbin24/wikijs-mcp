"""Configuration management for WikiJS MCP Server."""

import os

from pydantic import BaseModel, Field

DEFAULT_MCP_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*"]
DEFAULT_MCP_ALLOWED_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*"]


def parse_bool(value: str | None, default: bool = False) -> bool:
    """Parse common environment-style boolean values."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_csv_list(value: str | None, default: list[str]) -> list[str]:
    """Parse comma-separated environment values into a clean list."""
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


class WikiJSConfig(BaseModel):
    """Configuration for Wiki.js connection."""

    url: str = Field(default="")
    api_key: str = Field(default="")
    graphql_endpoint: str = Field(default="/graphql")
    debug: bool = Field(default=False)
    read_only: bool = Field(default=False)
    mcp_host: str = Field(default="127.0.0.1")
    mcp_port: int = Field(default=8000)
    mcp_path: str = Field(default="/mcp")
    mcp_allowed_hosts: list[str] = Field(default_factory=lambda: list(DEFAULT_MCP_ALLOWED_HOSTS))
    mcp_allowed_origins: list[str] = Field(
        default_factory=lambda: list(DEFAULT_MCP_ALLOWED_ORIGINS)
    )

    @classmethod
    def load_config(cls) -> "WikiJSConfig":
        """Load configuration from environment variables."""
        return cls(
            url=os.getenv("WIKIJS_URL", ""),
            api_key=os.getenv("WIKIJS_API_KEY", ""),
            graphql_endpoint=os.getenv("WIKIJS_GRAPHQL_ENDPOINT", "/graphql"),
            debug=parse_bool(os.getenv("DEBUG")),
            read_only=parse_bool(os.getenv("WIKIJS_READ_ONLY")),
            mcp_host=os.getenv("MCP_HOST", "127.0.0.1"),
            mcp_port=int(os.getenv("MCP_PORT", "8000")),
            mcp_path=os.getenv("MCP_PATH", "/mcp"),
            mcp_allowed_hosts=parse_csv_list(
                os.getenv("MCP_ALLOWED_HOSTS"), DEFAULT_MCP_ALLOWED_HOSTS
            ),
            mcp_allowed_origins=parse_csv_list(
                os.getenv("MCP_ALLOWED_ORIGINS"), DEFAULT_MCP_ALLOWED_ORIGINS
            ),
        )

    @property
    def graphql_url(self) -> str:
        """Get the full GraphQL endpoint URL."""
        return f"{self.url.rstrip('/')}{self.graphql_endpoint}"

    @property
    def headers(self) -> dict[str, str]:
        """Get authentication headers for API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def validate_config(self) -> None:
        """Validate that required configuration is present."""
        if not self.url:
            raise ValueError("WIKIJS_URL environment variable must be set.")
        if not self.api_key:
            raise ValueError("WIKIJS_API_KEY environment variable must be set.")
