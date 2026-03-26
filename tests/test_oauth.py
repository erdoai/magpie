"""Tests for MCP OAuth implementation."""

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import AnyUrl

from magpie.mcp.oauth import (
    ACCESS_TOKEN_TTL,
    AUTH_CODE_TTL,
    REFRESH_TOKEN_TTL,
    MagpieAccessToken,
    MagpieAuthCode,
    MagpieOAuthProvider,
    MagpieRefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull


# -- Fixtures --


def _make_pool():
    """Create a mock asyncpg pool."""
    pool = AsyncMock()
    return pool


def _make_db(pool=None):
    """Create a mock Database with a pool."""
    db = MagicMock()
    db._pool = pool or _make_pool()
    return db


def _make_provider(db=None, issuer_url="https://magpie.erdo.ai"):
    db = db or _make_db()
    return MagpieOAuthProvider(db, issuer_url), db


def _make_client_info(**overrides):
    defaults = {
        "client_id": "test-client-123",
        "client_secret": None,
        "client_id_issued_at": int(time.time()),
        "client_secret_expires_at": None,
        "redirect_uris": ["https://example.com/callback"],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_name": "Test Client",
        "scope": "read write",
    }
    defaults.update(overrides)
    return OAuthClientInformationFull(**defaults)


# -- get_client --


async def test_get_client_found():
    provider, db = _make_provider()
    db._pool.fetchrow.return_value = {
        "client_id": "c1",
        "client_secret": None,
        "client_id_issued_at": 1000,
        "client_secret_expires_at": None,
        "redirect_uris": ["https://example.com/cb"],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "client_name": "My App",
        "client_uri": None,
        "logo_uri": None,
        "scope": "read",
        "contacts": None,
        "tos_uri": None,
        "policy_uri": None,
        "software_id": None,
        "software_version": None,
    }

    result = await provider.get_client("c1")
    assert result is not None
    assert result.client_id == "c1"
    assert result.client_name == "My App"


async def test_get_client_not_found():
    provider, db = _make_provider()
    db._pool.fetchrow.return_value = None

    result = await provider.get_client("nonexistent")
    assert result is None


# -- register_client --


async def test_register_client():
    provider, db = _make_provider()
    client = _make_client_info()

    await provider.register_client(client)
    db._pool.execute.assert_called_once()
    args = db._pool.execute.call_args[0]
    assert "INSERT INTO oauth_clients" in args[0]
    assert args[1] == "test-client-123"


# -- authorize --


async def test_authorize_returns_consent_url():
    from mcp.server.auth.provider import AuthorizationParams

    provider, _ = _make_provider(issuer_url="https://magpie.erdo.ai")
    client = _make_client_info()
    params = AuthorizationParams(
        state="abc123",
        scopes=["read", "write"],
        code_challenge="challenge_value",
        redirect_uri=AnyUrl("https://example.com/callback"),
        redirect_uri_provided_explicitly=True,
        resource=None,
    )

    url = await provider.authorize(client, params)
    assert url.startswith("https://magpie.erdo.ai/oauth/authorize?")
    assert "client_id=test-client-123" in url
    assert "state=abc123" in url
    assert "code_challenge=challenge_value" in url


async def test_authorize_without_optional_params():
    from mcp.server.auth.provider import AuthorizationParams

    provider, _ = _make_provider()
    client = _make_client_info()
    params = AuthorizationParams(
        state=None,
        scopes=None,
        code_challenge="ch",
        redirect_uri=AnyUrl("https://example.com/callback"),
        redirect_uri_provided_explicitly=False,
    )

    url = await provider.authorize(client, params)
    assert "state" not in url
    assert "scope" not in url
    assert "code_challenge=ch" in url


# -- load_authorization_code --


async def test_load_authorization_code_found():
    provider, db = _make_provider()
    expires = datetime.now(UTC) + timedelta(minutes=5)
    db._pool.fetchrow.return_value = {
        "code": "authcode123",
        "client_id": "c1",
        "user_id": "u1",
        "scopes": ["read"],
        "redirect_uri": "https://example.com/cb",
        "redirect_uri_provided_explicitly": True,
        "code_challenge": "ch",
        "resource": None,
        "expires_at": expires,
    }

    client = _make_client_info(client_id="c1")
    result = await provider.load_authorization_code(client, "authcode123")
    assert isinstance(result, MagpieAuthCode)
    assert result.code == "authcode123"
    assert result.user_id == "u1"


async def test_load_authorization_code_not_found():
    provider, db = _make_provider()
    db._pool.fetchrow.return_value = None

    client = _make_client_info()
    result = await provider.load_authorization_code(client, "bad")
    assert result is None


# -- exchange_authorization_code --


async def test_exchange_authorization_code():
    provider, db = _make_provider()
    client = _make_client_info(client_id="c1")
    auth_code = MagpieAuthCode(
        code="code1",
        client_id="c1",
        user_id="u1",
        scopes=["read"],
        redirect_uri=AnyUrl("https://example.com/cb"),
        redirect_uri_provided_explicitly=True,
        code_challenge="ch",
        expires_at=time.time() + 300,
        resource=None,
    )

    token = await provider.exchange_authorization_code(client, auth_code)

    assert token.access_token
    assert token.refresh_token
    assert token.token_type == "Bearer"
    assert token.expires_in == ACCESS_TOKEN_TTL
    assert token.scope == "read"

    # Should have: delete code, insert access token, insert refresh token
    assert db._pool.execute.call_count == 3


# -- load_refresh_token --


async def test_load_refresh_token_found():
    provider, db = _make_provider()
    expires = datetime.now(UTC) + timedelta(days=30)
    db._pool.fetchrow.return_value = {
        "token": "rt1",
        "client_id": "c1",
        "user_id": "u1",
        "scopes": ["read", "write"],
        "expires_at": expires,
    }

    client = _make_client_info(client_id="c1")
    result = await provider.load_refresh_token(client, "rt1")
    assert isinstance(result, MagpieRefreshToken)
    assert result.token == "rt1"
    assert result.user_id == "u1"


async def test_load_refresh_token_expired():
    provider, db = _make_provider()
    expired = datetime.now(UTC) - timedelta(hours=1)
    db._pool.fetchrow.return_value = {
        "token": "rt_old",
        "client_id": "c1",
        "user_id": "u1",
        "scopes": ["read"],
        "expires_at": expired,
    }

    client = _make_client_info(client_id="c1")
    result = await provider.load_refresh_token(client, "rt_old")
    assert result is None
    # Should delete expired token
    db._pool.execute.assert_called_once()


async def test_load_refresh_token_not_found():
    provider, db = _make_provider()
    db._pool.fetchrow.return_value = None

    client = _make_client_info()
    result = await provider.load_refresh_token(client, "nope")
    assert result is None


# -- exchange_refresh_token --


async def test_exchange_refresh_token():
    provider, db = _make_provider()
    client = _make_client_info(client_id="c1")
    refresh = MagpieRefreshToken(
        token="rt1",
        client_id="c1",
        user_id="u1",
        scopes=["read", "write"],
    )

    token = await provider.exchange_refresh_token(client, refresh, scopes=[])

    assert token.access_token
    assert token.refresh_token
    assert token.token_type == "Bearer"
    assert token.expires_in == ACCESS_TOKEN_TTL
    # Empty scopes = inherit from refresh token
    assert token.scope == "read write"

    # delete old refresh, delete old access, insert access, insert refresh
    assert db._pool.execute.call_count == 4


async def test_exchange_refresh_token_with_scopes():
    provider, db = _make_provider()
    client = _make_client_info(client_id="c1")
    refresh = MagpieRefreshToken(
        token="rt1",
        client_id="c1",
        user_id="u1",
        scopes=["read", "write"],
    )

    token = await provider.exchange_refresh_token(
        client, refresh, scopes=["read"]
    )
    assert token.scope == "read"


# -- load_access_token --


async def test_load_access_token_found():
    provider, db = _make_provider()
    expires = datetime.now(UTC) + timedelta(hours=1)
    db._pool.fetchrow.return_value = {
        "token": "at1",
        "client_id": "c1",
        "user_id": "u1",
        "scopes": ["read"],
        "resource": None,
        "expires_at": expires,
    }

    result = await provider.load_access_token("at1")
    assert isinstance(result, MagpieAccessToken)
    assert result.token == "at1"
    assert result.user_id == "u1"


async def test_load_access_token_expired():
    provider, db = _make_provider()
    expired = datetime.now(UTC) - timedelta(hours=1)
    db._pool.fetchrow.return_value = {
        "token": "at_old",
        "client_id": "c1",
        "user_id": "u1",
        "scopes": ["read"],
        "resource": None,
        "expires_at": expired,
    }

    result = await provider.load_access_token("at_old")
    assert result is None
    db._pool.execute.assert_called_once()


async def test_load_access_token_not_found():
    provider, db = _make_provider()
    db._pool.fetchrow.return_value = None

    result = await provider.load_access_token("nope")
    assert result is None


# -- revoke_token --


async def test_revoke_access_token():
    provider, db = _make_provider()
    token = MagpieAccessToken(
        token="at1",
        client_id="c1",
        user_id="u1",
        scopes=["read"],
    )

    await provider.revoke_token(token)
    # Should delete both access token and related refresh tokens
    assert db._pool.execute.call_count == 2


async def test_revoke_refresh_token():
    provider, db = _make_provider()
    token = MagpieRefreshToken(
        token="rt1",
        client_id="c1",
        user_id="u1",
        scopes=["read"],
    )

    await provider.revoke_token(token)
    # Should delete both refresh token and related access tokens
    assert db._pool.execute.call_count == 2


# -- create_authorization_code --


async def test_create_authorization_code():
    provider, db = _make_provider()

    redirect_url = await provider.create_authorization_code(
        client_id="c1",
        user_id="u1",
        redirect_uri="https://example.com/callback",
        redirect_uri_provided_explicitly=True,
        code_challenge="ch",
        scopes=["read"],
        state="mystate",
    )

    assert redirect_url.startswith("https://example.com/callback?")
    assert "code=" in redirect_url
    assert "state=mystate" in redirect_url
    db._pool.execute.assert_called_once()


async def test_create_authorization_code_no_state():
    provider, db = _make_provider()

    redirect_url = await provider.create_authorization_code(
        client_id="c1",
        user_id="u1",
        redirect_uri="https://example.com/callback",
        redirect_uri_provided_explicitly=True,
        code_challenge="ch",
    )

    assert "code=" in redirect_url
    assert "state" not in redirect_url


# -- MCP server creation --


def test_create_mcp_server_without_oauth():
    from magpie.mcp.server import create_mcp_server

    server = create_mcp_server()
    assert server is not None
    assert server.name == "magpie"


def test_create_mcp_server_with_oauth():
    from magpie.mcp.server import create_mcp_server

    db = _make_db()
    provider = MagpieOAuthProvider(db, "https://magpie.erdo.ai")

    server = create_mcp_server(
        oauth_issuer_url="https://magpie.erdo.ai",
        oauth_provider=provider,
    )
    assert server is not None
    assert server.settings.auth is not None
    assert str(server.settings.auth.issuer_url) == "https://magpie.erdo.ai/"
