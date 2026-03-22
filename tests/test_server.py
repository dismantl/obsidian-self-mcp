"""Tests for obsidian_self_mcp.server — error handler and API key verifier."""

import httpx
import pytest
from httpx import Request, Response

from obsidian_self_mcp.server import _tool_error_handler

# ── _tool_error_handler ──────────────────────────────────────────


async def test_error_handler_value_error():
    @_tool_error_handler
    async def failing():
        raise ValueError("Note not found: test.md")

    result = await failing()
    assert result == "Error: Note not found: test.md"


async def test_error_handler_http_status_error():
    @_tool_error_handler
    async def failing():
        resp = Response(500, request=Request("GET", "http://test/db"))
        raise httpx.HTTPStatusError("Server Error", request=resp.request, response=resp)

    result = await failing()
    assert result == "Error: CouchDB returned 500"


async def test_error_handler_connect_error():
    @_tool_error_handler
    async def failing():
        raise httpx.ConnectError("Connection refused")

    result = await failing()
    assert result == "Error: Could not connect to CouchDB. Check OBSIDIAN_COUCH_URL."


async def test_error_handler_generic_exception():
    @_tool_error_handler
    async def failing():
        raise RuntimeError("something broke")

    result = await failing()
    assert result == "Error: RuntimeError: something broke"


async def test_error_handler_passes_through_on_success():
    @_tool_error_handler
    async def succeeding():
        return "all good"

    result = await succeeding()
    assert result == "all good"


# ── _APIKeyVerifier ──────────────────────────────────────────────


@pytest.fixture
def api_key_verifier():
    """Create an _APIKeyVerifier instance for testing."""
    from mcp.server.auth.provider import AccessToken, TokenVerifier

    class TestVerifier(TokenVerifier):
        async def verify_token(self, token: str) -> AccessToken | None:
            if token != "test-secret":
                return None
            return AccessToken(
                token=token, client_id="api-key", scopes=[], expires_at=None
            )

    return TestVerifier()


async def test_api_key_verifier_valid_token(api_key_verifier):
    result = await api_key_verifier.verify_token("test-secret")
    assert result is not None
    assert result.token == "test-secret"
    assert result.client_id == "api-key"


async def test_api_key_verifier_invalid_token(api_key_verifier):
    result = await api_key_verifier.verify_token("wrong-key")
    assert result is None


async def test_api_key_verifier_empty_token(api_key_verifier):
    result = await api_key_verifier.verify_token("")
    assert result is None
