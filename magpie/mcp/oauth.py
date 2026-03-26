"""OAuth 2.0 Authorization Server Provider for MCP.

Implements the MCP SDK's OAuthAuthorizationServerProvider protocol,
backed by Postgres. Handles dynamic client registration, authorization
codes, access tokens, and refresh tokens.

The authorization flow redirects to /oauth/authorize — a consent page
where the user authenticates (via existing session or email OTP) and
approves the client.
"""

import logging
import secrets
import time
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from magpie.db.database import Database

logger = logging.getLogger(__name__)

# Token lifetimes
ACCESS_TOKEN_TTL = 3600  # 1 hour
REFRESH_TOKEN_TTL = 30 * 24 * 3600  # 30 days
AUTH_CODE_TTL = 300  # 5 minutes


class MagpieAuthCode(AuthorizationCode):
    """Authorization code with user association."""
    user_id: str


class MagpieAccessToken(AccessToken):
    """Access token with user association."""
    user_id: str


class MagpieRefreshToken(RefreshToken):
    """Refresh token with user association."""
    user_id: str


class MagpieOAuthProvider:
    """OAuth provider backed by Postgres.

    Implements OAuthAuthorizationServerProvider protocol.
    """

    def __init__(self, db: Database, issuer_url: str):
        self._db = db
        self._issuer_url = issuer_url.rstrip("/")

    # -- Client Registration --

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        row = await self._db._pool.fetchrow(
            "SELECT * FROM oauth_clients WHERE client_id = $1", client_id
        )
        if not row:
            return None
        return OAuthClientInformationFull(
            client_id=row["client_id"],
            client_secret=row["client_secret"],
            client_id_issued_at=row["client_id_issued_at"],
            client_secret_expires_at=row["client_secret_expires_at"],
            redirect_uris=row["redirect_uris"],
            token_endpoint_auth_method=row["token_endpoint_auth_method"],
            grant_types=row["grant_types"],
            response_types=row["response_types"],
            client_name=row["client_name"],
            client_uri=row["client_uri"],
            logo_uri=row["logo_uri"],
            scope=row["scope"],
            contacts=row["contacts"],
            tos_uri=row["tos_uri"],
            policy_uri=row["policy_uri"],
            software_id=row["software_id"],
            software_version=row["software_version"],
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await self._db._pool.execute(
            """INSERT INTO oauth_clients
               (client_id, client_secret, client_id_issued_at, client_secret_expires_at,
                redirect_uris, token_endpoint_auth_method, grant_types, response_types,
                client_name, client_uri, logo_uri, scope, contacts,
                tos_uri, policy_uri, software_id, software_version)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)""",
            client_info.client_id,
            client_info.client_secret,
            client_info.client_id_issued_at,
            client_info.client_secret_expires_at,
            [str(u) for u in client_info.redirect_uris] if client_info.redirect_uris else [],
            client_info.token_endpoint_auth_method or "none",
            (list(client_info.grant_types) if client_info.grant_types
             else ["authorization_code", "refresh_token"]),
            list(client_info.response_types) if client_info.response_types else ["code"],
            client_info.client_name,
            str(client_info.client_uri) if client_info.client_uri else None,
            str(client_info.logo_uri) if client_info.logo_uri else None,
            client_info.scope,
            list(client_info.contacts) if client_info.contacts else None,
            str(client_info.tos_uri) if client_info.tos_uri else None,
            str(client_info.policy_uri) if client_info.policy_uri else None,
            client_info.software_id,
            client_info.software_version,
        )
        logger.info(
            "Registered OAuth client: %s (%s)", client_info.client_id, client_info.client_name
        )

    # -- Authorization --

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Redirect to our consent page with the OAuth params."""
        query = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "redirect_uri_provided_explicitly": str(
                params.redirect_uri_provided_explicitly
            ).lower(),
        }
        if params.state:
            query["state"] = params.state
        if params.scopes:
            query["scope"] = " ".join(params.scopes)
        if params.resource:
            query["resource"] = str(params.resource)

        return f"{self._issuer_url}/oauth/authorize?{urlencode(query)}"

    # -- Authorization Code --

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> MagpieAuthCode | None:
        row = await self._db._pool.fetchrow(
            "SELECT * FROM oauth_authorization_codes WHERE code = $1 AND client_id = $2",
            authorization_code, client.client_id,
        )
        if not row:
            return None
        return MagpieAuthCode(
            code=row["code"],
            client_id=row["client_id"],
            user_id=row["user_id"],
            scopes=list(row["scopes"]),
            redirect_uri=AnyUrl(row["redirect_uri"]),
            redirect_uri_provided_explicitly=row["redirect_uri_provided_explicitly"],
            code_challenge=row["code_challenge"],
            resource=row["resource"],
            expires_at=row["expires_at"].timestamp(),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: MagpieAuthCode
    ) -> OAuthToken:
        # Delete used code
        await self._db._pool.execute(
            "DELETE FROM oauth_authorization_codes WHERE code = $1",
            authorization_code.code,
        )

        # Create access token
        access_token = secrets.token_urlsafe(32)
        now = int(time.time())
        access_expires = now + ACCESS_TOKEN_TTL

        await self._db._pool.execute(
            """INSERT INTO oauth_access_tokens
               (token, client_id, user_id, scopes, resource, expires_at)
               VALUES ($1, $2, $3, $4, $5, to_timestamp($6))""",
            access_token,
            client.client_id,
            authorization_code.user_id,
            authorization_code.scopes,
            authorization_code.resource,
            access_expires,
        )

        # Create refresh token
        refresh_token = secrets.token_urlsafe(32)
        refresh_expires = now + REFRESH_TOKEN_TTL

        await self._db._pool.execute(
            """INSERT INTO oauth_refresh_tokens
               (token, client_id, user_id, scopes, expires_at)
               VALUES ($1, $2, $3, $4, to_timestamp($5))""",
            refresh_token,
            client.client_id,
            authorization_code.user_id,
            authorization_code.scopes,
            refresh_expires,
        )

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
            refresh_token=refresh_token,
        )

    # -- Refresh Token --

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> MagpieRefreshToken | None:
        row = await self._db._pool.fetchrow(
            "SELECT * FROM oauth_refresh_tokens WHERE token = $1 AND client_id = $2",
            refresh_token, client.client_id,
        )
        if not row:
            return None
        # Check expiry
        if row["expires_at"] and row["expires_at"].timestamp() < time.time():
            await self._db._pool.execute(
                "DELETE FROM oauth_refresh_tokens WHERE token = $1", refresh_token
            )
            return None
        return MagpieRefreshToken(
            token=row["token"],
            client_id=row["client_id"],
            user_id=row["user_id"],
            scopes=list(row["scopes"]),
            expires_at=int(row["expires_at"].timestamp()) if row["expires_at"] else None,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: MagpieRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Rotate: delete old refresh token
        await self._db._pool.execute(
            "DELETE FROM oauth_refresh_tokens WHERE token = $1",
            refresh_token.token,
        )
        # Delete old access tokens for this client+user
        await self._db._pool.execute(
            "DELETE FROM oauth_access_tokens WHERE client_id = $1 AND user_id = $2",
            client.client_id, refresh_token.user_id,
        )

        effective_scopes = scopes if scopes else refresh_token.scopes
        now = int(time.time())

        # New access token
        access_token = secrets.token_urlsafe(32)
        access_expires = now + ACCESS_TOKEN_TTL

        await self._db._pool.execute(
            """INSERT INTO oauth_access_tokens
               (token, client_id, user_id, scopes, expires_at)
               VALUES ($1, $2, $3, $4, to_timestamp($5))""",
            access_token,
            client.client_id,
            refresh_token.user_id,
            effective_scopes,
            access_expires,
        )

        # New refresh token
        new_refresh = secrets.token_urlsafe(32)
        refresh_expires = now + REFRESH_TOKEN_TTL

        await self._db._pool.execute(
            """INSERT INTO oauth_refresh_tokens
               (token, client_id, user_id, scopes, expires_at)
               VALUES ($1, $2, $3, $4, to_timestamp($5))""",
            new_refresh,
            client.client_id,
            refresh_token.user_id,
            effective_scopes,
            refresh_expires,
        )

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            scope=" ".join(effective_scopes) if effective_scopes else None,
            refresh_token=new_refresh,
        )

    # -- Access Token --

    async def load_access_token(self, token: str) -> MagpieAccessToken | None:
        row = await self._db._pool.fetchrow(
            "SELECT * FROM oauth_access_tokens WHERE token = $1", token
        )
        if not row:
            return None
        # Check expiry
        if row["expires_at"].timestamp() < time.time():
            await self._db._pool.execute(
                "DELETE FROM oauth_access_tokens WHERE token = $1", token
            )
            return None
        return MagpieAccessToken(
            token=row["token"],
            client_id=row["client_id"],
            user_id=row["user_id"],
            scopes=list(row["scopes"]),
            resource=row["resource"],
            expires_at=int(row["expires_at"].timestamp()),
        )

    # -- Revocation --

    async def revoke_token(
        self, token: MagpieAccessToken | MagpieRefreshToken
    ) -> None:
        # Revoke both access and refresh tokens for the client+user
        if isinstance(token, MagpieAccessToken):
            await self._db._pool.execute(
                "DELETE FROM oauth_access_tokens WHERE token = $1", token.token
            )
            await self._db._pool.execute(
                "DELETE FROM oauth_refresh_tokens WHERE client_id = $1 AND user_id = $2",
                token.client_id, token.user_id,
            )
        elif isinstance(token, MagpieRefreshToken):
            await self._db._pool.execute(
                "DELETE FROM oauth_refresh_tokens WHERE token = $1", token.token
            )
            await self._db._pool.execute(
                "DELETE FROM oauth_access_tokens WHERE client_id = $1 AND user_id = $2",
                token.client_id, token.user_id,
            )

    # -- Helper: create authorization code (called from consent page) --

    async def create_authorization_code(
        self,
        client_id: str,
        user_id: str,
        redirect_uri: str,
        redirect_uri_provided_explicitly: bool,
        code_challenge: str,
        scopes: list[str] | None = None,
        state: str | None = None,
        resource: str | None = None,
    ) -> str:
        """Create and store an authorization code. Returns the redirect URL."""
        code = secrets.token_urlsafe(32)  # 256 bits of entropy
        from datetime import UTC, datetime, timedelta

        expires_at = datetime.now(UTC) + timedelta(seconds=AUTH_CODE_TTL)

        await self._db._pool.execute(
            """INSERT INTO oauth_authorization_codes
               (code, client_id, user_id, scopes, redirect_uri,
                redirect_uri_provided_explicitly, code_challenge, resource, expires_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
            code,
            client_id,
            user_id,
            scopes or [],
            redirect_uri,
            redirect_uri_provided_explicitly,
            code_challenge,
            resource,
            expires_at,
        )

        return construct_redirect_uri(redirect_uri, code=code, state=state)
