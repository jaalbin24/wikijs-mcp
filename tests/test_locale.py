"""Tests for the locale resolution and move verification fork features.

These tests never talk to a live wiki: all HTTP is routed through
``httpx.MockTransport``.
"""

import json
import os
from unittest.mock import patch

import httpx
import pytest

from wikijs_mcp.client import WikiJSClient
from wikijs_mcp.config import WikiJSConfig


def make_client(handler) -> WikiJSClient:
    """Build a WikiJSClient whose HTTP stack is a MockTransport handler."""
    config = WikiJSConfig(
        url="https://test-wiki.example.com",
        api_key="test-api-key-123",
        graphql_endpoint="/graphql",
    )
    client = WikiJSClient(config)
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def localization_handler(site_locale):
    """Return a MockTransport handler that answers GetLocalizationConfig.

    ``site_locale is None`` simulates an unknown/empty localization config.
    Raises for any other GraphQL operation.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graphql"
        body = json.loads(request.content)
        query = body["query"]
        if "GetLocalizationConfig" in query:
            if site_locale is None:
                data = {}
            else:
                data = {
                    "localization": {
                        "config": {
                            "locale": site_locale,
                            "autoUpdate": True,
                            "namespacing": False,
                            "namespaces": [site_locale],
                        }
                    }
                }
            return httpx.Response(200, json={"data": data})
        raise AssertionError(f"Unexpected GraphQL operation: {query}")

    return handler


@pytest.mark.unit
class TestResolveLocale:
    """_resolve_locale precedence: explicit > env > site locale > fallback 'de'."""

    async def test_explicit_locale_wins(self):
        with patch.dict(os.environ, {"WIKIJS_DEFAULT_LOCALE": "de"}):
            async with make_client(localization_handler("zh")) as client:
                assert await client._resolve_locale("fr") == "fr"
                # Explicit values are not cached as the default.
                assert client._resolved_locale is None

    async def test_env_override_beats_site_locale(self):
        with patch.dict(os.environ, {"WIKIJS_DEFAULT_LOCALE": "de"}):
            async with make_client(localization_handler("zh")) as client:
                assert await client._resolve_locale() == "de"

    async def test_config_default_locale_used(self):
        config = WikiJSConfig(
            url="https://test-wiki.example.com",
            api_key="k",
            default_locale="it",
        )
        client = WikiJSClient(config)
        client.client = httpx.AsyncClient(
            transport=httpx.MockTransport(localization_handler("zh"))
        )
        async with client:
            assert await client._resolve_locale() == "it"

    async def test_env_var_read_directly_when_config_lacks_default(self):
        # No default_locale on the config, but WIKIJS_DEFAULT_LOCALE set in env.
        async with make_client(localization_handler("zh")) as client:
            with patch.dict(os.environ, {"WIKIJS_DEFAULT_LOCALE": "de"}):
                assert await client._resolve_locale() == "de"

    async def test_site_primary_locale_used_as_fallback(self):
        async with make_client(localization_handler("zh")) as client:
            assert await client._resolve_locale() == "zh"

    async def test_fallback_is_de_not_en(self):
        async with make_client(localization_handler(None)) as client:
            assert await client._resolve_locale() == "de"

    async def test_result_cached_per_client_instance(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert "GetLocalizationConfig" in body["query"]
            calls["n"] += 1
            return httpx.Response(
                200,
                json={"data": {"localization": {"config": {"locale": "zh"}}}},
            )

        async with make_client(handler) as client:
            assert await client._resolve_locale() == "zh"
            assert await client._resolve_locale() == "zh"
            # The site locale is queried exactly once per client instance.
            assert calls["n"] == 1

    async def test_env_default_cached_after_first_resolution(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no GraphQL call expected: " + str(request.url))

        config = WikiJSConfig(
            url="https://test-wiki.example.com",
            api_key="k",
            default_locale="de",
        )
        client = WikiJSClient(config)
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        async with client:
            assert await client._resolve_locale() == "de"
            assert await client._resolve_locale() == "de"


def move_verification_handler(
    site_locale="de",
    *,
    result_path="docs/new",
    result_locale="de",
    result_page=None,
    page_missing=False,
):
    """Handler for move_page verification (success + mismatch scenarios)."""
    state = {"moved": False}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graphql"
        body = json.loads(request.content)
        query = body["query"]
        if "GetLocalizationConfig" in query:
            return httpx.Response(200, json={"data": {}})
        if "mutation MovePage" in query:
            state["moved"] = True
            return httpx.Response(
                200,
                json={
                    "data": {
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
                },
            )
        if "query GetPageById" in query:
            assert state["moved"], "verification ran before the move"
            if page_missing:
                page = None
            elif result_page is not None:
                page = result_page
            else:
                page = {
                    "id": 5,
                    "path": result_path,
                    "locale": result_locale,
                    "title": "Moved Page",
                }
            return httpx.Response(200, json={"data": {"pages": {"single": page}}})
        raise AssertionError(f"Unexpected GraphQL operation: {query}")

    return handler


@pytest.mark.unit
class TestMoveVerification:
    """Post-move verification: success + dirty-state detection."""

    async def test_move_verification_success(self):
        async with make_client(move_verification_handler()) as client:
            result = await client.move_page(5, "docs/new")
            assert result["responseResult"]["succeeded"] is True

    async def test_move_verification_success_with_explicit_locale(self):
        async with make_client(
            move_verification_handler(result_path="docs/new", result_locale="fr")
        ) as client:
            result = await client.move_page(5, "docs/new", "fr")
            assert result["responseResult"]["succeeded"] is True

    async def test_move_verification_path_mismatch_raises(self):
        async with make_client(
            move_verification_handler(result_path="docs/old", result_locale="de")
        ) as client:
            with pytest.raises(Exception, match="Move verification failed") as excinfo:
                await client.move_page(5, "docs/new")
            text = str(excinfo.value)
            assert "docs/new" in text  # expected path
            assert "docs/old" in text  # actual path
            assert "storage" in text.lower() or "out of sync" in text.lower()

    async def test_move_verification_locale_mismatch_raises(self):
        async with make_client(
            move_verification_handler(result_path="docs/new", result_locale="en")
        ) as client:
            with pytest.raises(Exception, match="Move verification failed") as excinfo:
                await client.move_page(5, "docs/new", "de")
            text = str(excinfo.value)
            assert "'de'" in text  # expected locale
            assert "'en'" in text  # actual locale

    async def test_move_verification_missing_page_raises(self):
        async with make_client(move_verification_handler(page_missing=True)) as client:
            with pytest.raises(Exception, match="Move verification failed") as excinfo:
                await client.move_page(5, "docs/new")
            assert "could not be found after the move" in str(excinfo.value)

    async def test_move_resolves_default_locale_sent_to_graphql(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            query = body["query"]
            if "GetLocalizationConfig" in query:
                return httpx.Response(200, json={"data": {}})
            if "mutation MovePage" in query:
                captured["variables"] = body["variables"]
                return httpx.Response(
                    200,
                    json={
                        "data": {
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
                    },
                )
            if "query GetPageById" in query:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "pages": {
                                "single": {
                                    "id": 5,
                                    "path": "docs/new",
                                    "locale": "de",
                                    "title": "X",
                                }
                            }
                        }
                    },
                )
            raise AssertionError(f"Unexpected GraphQL operation: {query}")

        async with make_client(handler) as client:
            await client.move_page(5, "docs/new")
        # The destination locale sent to the server is resolved (fallback 'de'),
        # not a hard-coded 'en'.
        assert captured["variables"]["destinationLocale"] == "de"
