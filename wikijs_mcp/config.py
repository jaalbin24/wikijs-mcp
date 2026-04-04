"""Configuration management for WikiJS MCP Server."""

import os
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv


class WikiJSConfig(BaseModel):
    """Configuration for Wiki.js connection."""

    url: str = Field(default="")
    api_key: str = Field(default="")
    graphql_endpoint: str = Field(default="/graphql")
    debug: bool = Field(default=False)

    @classmethod
    def load_config(cls, env_file: str = ".env") -> "WikiJSConfig":
        """Load configuration from .env file."""
        if os.path.exists(env_file):
            load_dotenv(env_file)
        else:
            print(
                f"No configuration found at {env_file}. Please create a .env file with your WikiJS settings."
            )

        return cls(
            url=os.getenv("WIKIJS_URL", ""),
            api_key=os.getenv("WIKIJS_API_KEY", ""),
            graphql_endpoint=os.getenv("WIKIJS_GRAPHQL_ENDPOINT", "/graphql"),
            debug=os.getenv("DEBUG", "false").lower() == "true",
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
            raise ValueError("WIKIJS_URL must be set in your .env file.")
        if not self.api_key:
            raise ValueError("WIKIJS_API_KEY must be set in your .env file.")
