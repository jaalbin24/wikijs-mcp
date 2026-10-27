"""Configuration management for WikiJS MCP Server."""

import json
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


def parse_mapping(value: str | None, *, normalize_keys: bool = False) -> dict[str, str]:
    """Parse JSON or comma-separated key/value mappings from environment."""
    if value is None or not value.strip():
        return {}

    stripped = value.strip()
    if stripped.startswith("{"):
        parsed = json.loads(stripped)
        if not isinstance(parsed, dict):
            raise ValueError("Mapping environment variable must contain a JSON object.")
        items = parsed.items()
    else:
        entries = [entry.strip() for entry in stripped.replace("\n", ",").split(",")]
        parsed_items: list[tuple[str, str]] = []
        for entry in entries:
            if not entry:
                continue
            separator = "=" if "=" in entry else ":"
            if separator not in entry:
                raise ValueError(f"Invalid mapping entry: {entry!r}")
            key, val = entry.split(separator, 1)
            parsed_items.append((key, val))
        items = parsed_items

    mapping: dict[str, str] = {}
    for key, val in items:
        clean_key = str(key).strip()
        clean_val = str(val).strip()
        if not clean_key or not clean_val:
            raise ValueError("Mapping entries must have non-empty keys and values.")
        if normalize_keys:
            clean_key = clean_key.casefold()
        mapping[clean_key] = clean_val
    return mapping


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
    mcp_allowed_hosts: list[str] = Field(
        default_factory=lambda: list(DEFAULT_MCP_ALLOWED_HOSTS)
    )
    mcp_allowed_origins: list[str] = Field(
        default_factory=lambda: list(DEFAULT_MCP_ALLOWED_ORIGINS)
    )
    cloudflare_access_issuer: str = Field(default="")
    cloudflare_access_audience: str = Field(default="")
    cloudflare_access_jwks_url: str = Field(default="")
    auth_users: dict[str, str] = Field(default_factory=dict)
    auth_profiles: dict[str, str] = Field(default_factory=dict)

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
            cloudflare_access_issuer=os.getenv("WIKIJS_CF_ACCESS_ISSUER", ""),
            cloudflare_access_audience=os.getenv("WIKIJS_CF_ACCESS_AUDIENCE", ""),
            cloudflare_access_jwks_url=os.getenv("WIKIJS_CF_ACCESS_JWKS_URL", ""),
            auth_users=parse_mapping(
                os.getenv("WIKIJS_AUTH_USERS"), normalize_keys=True
            ),
            auth_profiles=parse_mapping(os.getenv("WIKIJS_AUTH_PROFILES")),
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

    @property
    def multi_user_auth_enabled(self) -> bool:
        """Return True when Cloudflare-to-profile authorization is configured."""
        return bool(
            self.cloudflare_access_issuer
            or self.cloudflare_access_audience
            or self.cloudflare_access_jwks_url
            or self.auth_users
            or self.auth_profiles
        )

    def validate_config(self, *, require_api_key: bool = True) -> None:
        """Validate that required configuration is present."""
        if not self.url:
            raise ValueError("WIKIJS_URL environment variable must be set.")
        if require_api_key and not self.api_key:
            raise ValueError("WIKIJS_API_KEY environment variable must be set.")

    def validate_multi_user_auth_config(self) -> None:
        """Validate Cloudflare Access and credential mapping configuration."""
        self.validate_config(require_api_key=False)
        missing = []
        if not self.cloudflare_access_issuer:
            missing.append("WIKIJS_CF_ACCESS_ISSUER")
        if not self.cloudflare_access_audience:
            missing.append("WIKIJS_CF_ACCESS_AUDIENCE")
        if not self.cloudflare_access_jwks_url:
            missing.append("WIKIJS_CF_ACCESS_JWKS_URL")
        if not self.auth_users:
            missing.append("WIKIJS_AUTH_USERS")
        if not self.auth_profiles:
            missing.append("WIKIJS_AUTH_PROFILES")
        if missing:
            raise ValueError(
                "Multi-user Cloudflare Access mode requires: " + ", ".join(missing)
            )

        undefined_profiles = sorted(
            set(self.auth_users.values()) - set(self.auth_profiles)
        )
        if undefined_profiles:
            raise ValueError(
                "WIKIJS_AUTH_USERS references undefined profile(s): "
                + ", ".join(undefined_profiles)
            )
