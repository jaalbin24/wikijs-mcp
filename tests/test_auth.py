"""Tests for Cloudflare Access identity and credential mapping."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import jwt
import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from wikijs_mcp.auth import (
    AuthorizationError,
    CloudflareAccessVerifier,
    WikiJSCredentialResolver,
)
from wikijs_mcp.config import WikiJSConfig
from wikijs_mcp.server import CloudflareAccessMiddleware, WikiJSMCPServer

ISSUER = "https://team.cloudflareaccess.com"
AUDIENCE = "access-audience"


@pytest.fixture
def rsa_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


class FakeJWKClient:
    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self.public_key)


class FakeWikiJSClient:
    """Capture request-scoped API keys used by real HTTP tool calls."""

    seen_api_keys: list[str] = []
    started_count: int = 0
    gate_started: threading.Event | None = None
    gate_release: threading.Event | None = None

    def __init__(self, config):
        self.config = config
        self.seen_api_keys.append(config.api_key)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None

    created_pages: list[dict] = []

    async def get_localization_config(self):
        return {"locale": "zh", "namespacing": False, "namespaces": ["zh"]}

    async def create_page(self, **kwargs):
        self.created_pages.append(kwargs)
        return {"page": {"id": 42, "title": kwargs["title"], "path": kwargs["path"]}}

    async def get_site_info(self):
        return {
            "title": "Test Wiki",
            "host": "https://wiki.example.com",
            "localization": await self.get_localization_config(),
        }

    async def list_pages(self, *args, **kwargs):
        if self.gate_started is not None and self.gate_release is not None:
            type(self).started_count += 1
            if type(self).started_count >= 2:
                self.gate_started.set()
            await asyncio.to_thread(self.gate_release.wait)
        return []


def make_token(
    private_key,
    *,
    email: str = "user@example.com",
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    expires_delta: timedelta = timedelta(minutes=5),
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "exp": now + expires_delta,
            "iat": now,
            "email": email,
        },
        private_key,
        algorithm="RS256",
    )


def make_config() -> WikiJSConfig:
    return WikiJSConfig(
        url="https://wiki.example.com",
        api_key="legacy-key",
        cloudflare_access_issuer=ISSUER,
        cloudflare_access_audience=AUDIENCE,
        cloudflare_access_jwks_url=f"{ISSUER}/cdn-cgi/access/certs",
        auth_users={
            "admin@example.com": "admin",
            "friend1@example.com": "friends",
            "friend2@example.com": "friends",
        },
        auth_profiles={
            "admin": "WIKIJS_API_KEY_ADMIN",
            "friends": "WIKIJS_API_KEY_FRIENDS",
        },
        mcp_allowed_hosts=["testserver", "127.0.0.1:*"],
    )


def post_mcp(client: TestClient, assertion: str, request_id: int, method: str, params):
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        },
        headers={
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "cf-access-jwt-assertion": assertion,
            "mcp-protocol-version": "2025-06-18",
        },
    )


def initialize(client: TestClient, assertion: str):
    return post_mcp(
        client,
        assertion,
        1,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0.0.0"},
        },
    )


def call_list_pages(client: TestClient, assertion: str, request_id: int = 2):
    return post_mcp(
        client,
        assertion,
        request_id,
        "tools/call",
        {"name": "wiki_list_pages", "arguments": {"limit": 5}},
    )


def make_resolver(config: WikiJSConfig, public_key) -> WikiJSCredentialResolver:
    resolver = WikiJSCredentialResolver(config)
    resolver._verifier = CloudflareAccessVerifier(
        issuer=config.cloudflare_access_issuer,
        audience=config.cloudflare_access_audience,
        jwks_url=config.cloudflare_access_jwks_url,
        jwk_client_factory=lambda url: FakeJWKClient(public_key),
    )
    return resolver


@pytest.mark.unit
class TestCloudflareAccessAuth:
    def test_valid_identity_uses_profile_a_key(self, rsa_keys):
        private_key, public_key = rsa_keys
        resolver = make_resolver(make_config(), public_key)
        token = make_token(private_key, email="Admin@Example.com")

        with patch.dict("os.environ", {"WIKIJS_API_KEY_ADMIN": "admin-key"}):
            assert resolver.resolve_for_assertion(token) == "admin-key"

    def test_valid_identity_uses_profile_b_key(self, rsa_keys):
        private_key, public_key = rsa_keys
        resolver = make_resolver(make_config(), public_key)
        token = make_token(private_key, email="friend1@example.com")

        with patch.dict("os.environ", {"WIKIJS_API_KEY_FRIENDS": "friends-key"}):
            assert resolver.resolve_for_assertion(token) == "friends-key"

    def test_multiple_users_can_share_profile_b(self, rsa_keys):
        private_key, public_key = rsa_keys
        resolver = make_resolver(make_config(), public_key)
        friend1 = make_token(private_key, email="friend1@example.com")
        friend2 = make_token(private_key, email="friend2@example.com")

        with patch.dict("os.environ", {"WIKIJS_API_KEY_FRIENDS": "friends-key"}):
            assert resolver.resolve_for_assertion(friend1) == "friends-key"
            assert resolver.resolve_for_assertion(friend2) == "friends-key"

    def test_unknown_authenticated_user_is_rejected(self, rsa_keys):
        private_key, public_key = rsa_keys
        resolver = make_resolver(make_config(), public_key)
        token = make_token(private_key, email="unknown@example.com")

        with pytest.raises(AuthorizationError, match="not configured"):
            resolver.resolve_for_assertion(token)

    def test_invalid_jwt_is_rejected(self, rsa_keys):
        _, public_key = rsa_keys
        resolver = make_resolver(make_config(), public_key)

        with pytest.raises(AuthorizationError, match="Invalid Cloudflare"):
            resolver.resolve_for_assertion("not-a-jwt")

    def test_expired_jwt_is_rejected(self, rsa_keys):
        private_key, public_key = rsa_keys
        resolver = make_resolver(make_config(), public_key)
        token = make_token(private_key, expires_delta=timedelta(minutes=-1))

        with pytest.raises(AuthorizationError, match="Invalid Cloudflare"):
            resolver.resolve_for_assertion(token)

    @pytest.mark.parametrize(
        "issuer,audience",
        [
            ("https://wrong.cloudflareaccess.com", AUDIENCE),
            (ISSUER, "wrong-audience"),
        ],
    )
    def test_wrong_audience_or_issuer_is_rejected(self, rsa_keys, issuer, audience):
        private_key, public_key = rsa_keys
        resolver = make_resolver(make_config(), public_key)
        token = make_token(private_key, issuer=issuer, audience=audience)

        with pytest.raises(AuthorizationError, match="Invalid Cloudflare"):
            resolver.resolve_for_assertion(token)

    def test_missing_configured_api_key_fails_closed(self, rsa_keys):
        private_key, public_key = rsa_keys
        resolver = make_resolver(make_config(), public_key)
        token = make_token(private_key, email="admin@example.com")

        with pytest.raises(AuthorizationError, match="environment variable"):
            resolver.resolve_for_assertion(token)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    async def test_request_scoped_resolution_does_not_mutate_global_config(
        self, mock_load_config, mock_wiki_config
    ):
        config = mock_wiki_config.model_copy(
            update={
                "api_key": "legacy-key",
                "cloudflare_access_issuer": ISSUER,
                "cloudflare_access_audience": AUDIENCE,
                "cloudflare_access_jwks_url": f"{ISSUER}/cdn-cgi/access/certs",
                "auth_users": {"a@example.com": "a", "b@example.com": "b"},
                "auth_profiles": {"a": "KEY_A", "b": "KEY_B"},
            }
        )
        mock_load_config.return_value = config
        server = WikiJSMCPServer()

        def fake_resolve(assertion):
            return {"assertion-a": "api-key-a", "assertion-b": "api-key-b"}[assertion]

        server.credential_resolver.resolve_for_assertion = fake_resolve

        async def resolve(assertion):
            request = SimpleNamespace(headers={"cf-access-jwt-assertion": assertion})
            return server._request_config_for_request(request).api_key

        result_a, result_b = await asyncio.gather(
            resolve("assertion-a"), resolve("assertion-b")
        )

        assert result_a == "api-key-a"
        assert result_b == "api-key-b"
        assert server.config.api_key == "legacy-key"

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    def test_missing_assertion_raises_tool_error(
        self, mock_load_config, mock_wiki_config
    ):
        config = mock_wiki_config.model_copy(
            update={
                "cloudflare_access_issuer": ISSUER,
                "cloudflare_access_audience": AUDIENCE,
                "cloudflare_access_jwks_url": f"{ISSUER}/cdn-cgi/access/certs",
                "auth_users": {"a@example.com": "a"},
                "auth_profiles": {"a": "KEY_A"},
            }
        )
        mock_load_config.return_value = config
        server = WikiJSMCPServer()
        request = SimpleNamespace(headers={})

        with pytest.raises(ToolError, match="Missing Cloudflare Access assertion"):
            server._request_config_for_request(request)

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    def test_missing_request_context_in_multi_user_fails_closed(
        self, mock_load_config, mock_wiki_config
    ):
        config = mock_wiki_config.model_copy(
            update={
                "api_key": "legacy-admin-key",
                "cloudflare_access_issuer": ISSUER,
                "cloudflare_access_audience": AUDIENCE,
                "cloudflare_access_jwks_url": f"{ISSUER}/cdn-cgi/access/certs",
                "auth_users": {"a@example.com": "a"},
                "auth_profiles": {"a": "KEY_A"},
            }
        )
        mock_load_config.return_value = config
        server = WikiJSMCPServer()

        with pytest.raises(ToolError, match="Request context unavailable"):
            server._request_config()

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    def test_request_config_uses_prevalidated_asgi_scope(
        self, mock_load_config, mock_wiki_config
    ):
        config = mock_wiki_config.model_copy(
            update={
                "cloudflare_access_issuer": ISSUER,
                "cloudflare_access_audience": AUDIENCE,
                "cloudflare_access_jwks_url": f"{ISSUER}/cdn-cgi/access/certs",
                "auth_users": {"a@example.com": "a"},
                "auth_profiles": {"a": "KEY_A"},
            }
        )
        mock_load_config.return_value = config
        server = WikiJSMCPServer()
        server.credential_resolver.resolve_for_assertion = lambda assertion: (
            pytest.fail(
                "resolver should not run when middleware already validated the request"
            )
        )
        request = SimpleNamespace(headers={}, scope={"wikijs_api_key": "scoped-key"})

        assert server._request_config_for_request(request).api_key == "scoped-key"

    async def test_cloudflare_middleware_rejects_missing_assertion(self):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        config = make_config()
        middleware = CloudflareAccessMiddleware(app, WikiJSCredentialResolver(config))
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        await middleware(
            {"type": "http", "headers": []},
            receive,
            send,
        )

        assert sent[0]["status"] == 401
        assert b"Cloudflare Access assertion" in sent[1]["body"]

    @pytest.mark.parametrize(
        ("tool", "arguments", "expected_text"),
        [
            (
                "wiki_create_page",
                {"path": "new-page", "title": "New page", "content": "Body"},
                "Successfully created page",
            ),
            ("wiki_get_site_info", {}, "Default Locale:** zh"),
        ],
    )
    @pytest.mark.parametrize(
        ("assertion", "api_key"),
        [("token-admin", "admin-key"), ("token-restricted", "restricted-key")],
    )
    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient", FakeWikiJSClient)
    def test_localized_http_tools_preserve_request_credentials(
        self, mock_load_config, tool, arguments, expected_text, assertion, api_key
    ):
        """Upstream locale support must not replace the caller's Wiki.js key."""
        mock_load_config.return_value = make_config()
        FakeWikiJSClient.seen_api_keys = []
        FakeWikiJSClient.created_pages = []
        server = WikiJSMCPServer()
        server.credential_resolver.resolve_for_assertion = lambda value: {
            assertion: api_key
        }[value]

        with TestClient(server.streamable_http_app()) as client:
            assert initialize(client, assertion).status_code == 200
            response = post_mcp(
                client,
                assertion,
                2,
                "tools/call",
                {"name": tool, "arguments": arguments},
            )

        assert response.status_code == 200
        assert not response.json()["result"].get("isError", False)
        assert expected_text in response.text
        assert FakeWikiJSClient.seen_api_keys == [api_key]
        assert server.config.api_key == "legacy-key"
        if tool == "wiki_create_page":
            assert FakeWikiJSClient.created_pages == [
                {
                    **arguments,
                    "description": "",
                    "tags": [],
                    "editor": "markdown",
                    "locale": "zh",
                }
            ]

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient", FakeWikiJSClient)
    def test_http_tool_call_uses_admin_request_scoped_key(self, mock_load_config):
        config = make_config()
        mock_load_config.return_value = config
        FakeWikiJSClient.seen_api_keys = []
        server = WikiJSMCPServer()
        server.credential_resolver.resolve_for_assertion = lambda assertion: {
            "token-admin": "admin-key"
        }[assertion]

        with TestClient(server.streamable_http_app()) as client:
            assert initialize(client, "token-admin").status_code == 200
            response = call_list_pages(client, "token-admin")

        assert response.status_code == 200
        assert FakeWikiJSClient.seen_api_keys == ["admin-key"]
        assert server.config.api_key == "legacy-key"

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient", FakeWikiJSClient)
    def test_http_tool_call_uses_restricted_request_scoped_key(self, mock_load_config):
        config = make_config()
        mock_load_config.return_value = config
        FakeWikiJSClient.seen_api_keys = []
        server = WikiJSMCPServer()
        server.credential_resolver.resolve_for_assertion = lambda assertion: {
            "token-restricted": "restricted-key"
        }[assertion]

        with TestClient(server.streamable_http_app()) as client:
            assert initialize(client, "token-restricted").status_code == 200
            response = call_list_pages(client, "token-restricted")

        assert response.status_code == 200
        assert FakeWikiJSClient.seen_api_keys == ["restricted-key"]
        assert server.config.api_key == "legacy-key"

    @patch("wikijs_mcp.server.WikiJSConfig.load_config")
    @patch("wikijs_mcp.server.WikiJSClient", FakeWikiJSClient)
    def test_http_concurrent_tool_calls_do_not_share_credentials(
        self, mock_load_config
    ):
        config = make_config()
        mock_load_config.return_value = config
        FakeWikiJSClient.seen_api_keys = []
        FakeWikiJSClient.started_count = 0
        FakeWikiJSClient.gate_started = threading.Event()
        FakeWikiJSClient.gate_release = threading.Event()
        server = WikiJSMCPServer()
        server.credential_resolver.resolve_for_assertion = lambda assertion: {
            "token-admin": "admin-key",
            "token-restricted": "restricted-key",
        }[assertion]

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        uvicorn_server = uvicorn.Server(
            uvicorn.Config(
                server.streamable_http_app(),
                host="127.0.0.1",
                port=port,
                log_level="warning",
            )
        )

        thread = threading.Thread(target=uvicorn_server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if uvicorn_server.started:
                break
            time.sleep(0.05)
        else:
            pytest.fail("uvicorn server did not start")

        async def flow(assertion: str, request_id: int) -> tuple[int, str]:
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                headers = {
                    "accept": "application/json, text/event-stream",
                    "content-type": "application/json",
                    "cf-access-jwt-assertion": assertion,
                    "mcp-protocol-version": "2025-06-18",
                }

                init_response = await client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {"name": "pytest", "version": "0.0.0"},
                        },
                    },
                    headers=headers,
                )
                assert init_response.status_code == 200

                response = await client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": request_id + 100,
                        "method": "tools/call",
                        "params": {
                            "name": "wiki_list_pages",
                            "arguments": {"limit": 5},
                        },
                    },
                    headers=headers,
                )
                return response.status_code, response.text

        async def run_flows() -> tuple[tuple[int, str], tuple[int, str]]:
            admin_task = asyncio.create_task(flow("token-admin", 1))
            restricted_task = asyncio.create_task(flow("token-restricted", 2))

            assert await asyncio.to_thread(FakeWikiJSClient.gate_started.wait, 5)
            FakeWikiJSClient.gate_release.set()

            admin_result = await admin_task
            restricted_result = await restricted_task
            return admin_result, restricted_result

        try:
            (admin_status, admin_body), (restricted_status, restricted_body) = (
                asyncio.run(run_flows())
            )
        finally:
            uvicorn_server.should_exit = True
            thread.join(timeout=10)

        assert admin_status == 200
        assert restricted_status == 200
        assert Counter(FakeWikiJSClient.seen_api_keys) == Counter(
            ["admin-key", "restricted-key"]
        )
        assert server.config.api_key == "legacy-key"
