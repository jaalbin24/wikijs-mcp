"""Cloudflare Access identity validation and Wiki.js credential mapping."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

import jwt
from jwt import PyJWKClient

from .config import WikiJSConfig

logger = logging.getLogger(__name__)


class AuthorizationError(Exception):
    """Raised when request identity or credential resolution fails."""


def normalize_email(email: str) -> str:
    """Normalize email identities for mapping lookups."""
    return email.strip().casefold()


class CloudflareAccessVerifier:
    """Validate Cloudflare Access JWT assertions."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        jwk_client_factory: Callable[[str], PyJWKClient] = PyJWKClient,
    ):
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.jwks_url = jwks_url
        self._jwk_client = jwk_client_factory(jwks_url)

    def validate(self, token: str) -> dict[str, Any]:
        """Validate a Cloudflare Access JWT and return its claims."""
        if not token:
            raise AuthorizationError("Missing Cloudflare Access assertion.")

        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            logger.warning(
                "Rejected Cloudflare Access assertion: %s", exc.__class__.__name__
            )
            raise AuthorizationError("Invalid Cloudflare Access assertion.") from exc


class WikiJSCredentialResolver:
    """Resolve the effective Wiki.js API key for a request."""

    def __init__(self, config: WikiJSConfig):
        self.config = config
        self._verifier: CloudflareAccessVerifier | None = None

    @property
    def verifier(self) -> CloudflareAccessVerifier:
        """Build the Cloudflare verifier lazily so startup stays lightweight."""
        if self._verifier is None:
            self._verifier = CloudflareAccessVerifier(
                issuer=self.config.cloudflare_access_issuer,
                audience=self.config.cloudflare_access_audience,
                jwks_url=self.config.cloudflare_access_jwks_url,
            )
        return self._verifier

    def resolve_for_assertion(self, assertion: str | None) -> str:
        """Resolve an API key from a Cloudflare Access JWT assertion."""
        if not assertion:
            raise AuthorizationError("Missing Cloudflare Access assertion.")

        claims = self.verifier.validate(assertion)
        email = self._extract_email(claims)
        profile = self.config.auth_users.get(normalize_email(email))
        if profile is None:
            raise AuthorizationError(
                "Authenticated user is not configured for Wiki.js access."
            )

        api_key_env = self.config.auth_profiles.get(profile)
        if api_key_env is None:
            raise AuthorizationError(
                "Configured Wiki.js credential profile does not exist."
            )

        api_key = os.getenv(api_key_env)
        if not api_key:
            raise AuthorizationError(
                f"Wiki.js API key environment variable for profile '{profile}' is not set."
            )

        return api_key

    @staticmethod
    def _extract_email(claims: dict[str, Any]) -> str:
        value = claims.get("email")
        if isinstance(value, str) and value.strip():
            return value

        raise AuthorizationError(
            "Cloudflare Access assertion does not contain an email identity."
        )
