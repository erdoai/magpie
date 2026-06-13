"""Auth middleware — supports API keys (bearer token) + session cookies."""

import hashlib
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from magpie.server.context import ORG_FORBIDDEN, resolve_active_org

logger = logging.getLogger(__name__)

# Client-supplied hint for which org a multi-org user is acting in. Validated
# against membership server-side — never trusted as-is.
ORG_HEADER = "x-organization-id"

PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

# Auth routes that don't require an existing session/key
AUTH_PATHS = {"/api/auth/send-code", "/api/auth/verify-code", "/api/auth/me"}


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = request.app.state.settings

        # Public paths
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Auth endpoints (login flow) — always accessible
        if request.url.path in AUTH_PATHS:
            return await call_next(request)

        # Static assets and SPA HTML — public
        if request.url.path.startswith("/assets") or (
            not request.url.path.startswith("/api")
            and not request.url.path.startswith("/mcp")
        ):
            return await call_next(request)

        # No auth configured at all — allow everything (unrestricted context)
        if not settings.api_key and not settings.resend_api_key:
            return await call_next(request)

        # Try to authenticate via bearer token or session cookie

        # 1. Bearer token (API keys)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

            # Static API key — unrestricted, single-tenant mode
            if settings.api_key and token == settings.api_key:
                request.state.user_id = None
                request.state.org_id = None
                request.state.role = None
                return await call_next(request)

            # Per-user API key — carries org/workspace/project scope and role
            db = request.app.state.db
            key_record = await db.get_api_key_by_hash(hash_key(token))
            if key_record:
                await db.touch_api_key(key_record["id"])
                request.state.user_id = key_record.get("user_id")
                request.state.org_id = key_record.get("org_id")
                request.state.role = key_record.get("role") or "editor"
                request.state.auth_workspace = key_record.get("workspace")
                request.state.auth_project = key_record.get("project")
                return await call_next(request)

        # 2. Session cookie
        session_id = request.cookies.get("magpie_session")
        if session_id:
            db = request.app.state.db
            session = await db.get_session(session_id)
            if session:
                request.state.user_id = session["user_id"]
                # Active org: X-Organization-ID header (validated) > saved
                # default > first membership. A header naming an org the user
                # isn't in is rejected, not silently downgraded.
                requested = request.headers.get(ORG_HEADER) or None
                org_id, role = await resolve_active_org(
                    db, session["user_id"], requested
                )
                if org_id is ORG_FORBIDDEN:
                    return JSONResponse(
                        status_code=403,
                        content={"error": "Not a member of the requested organization"},
                    )
                request.state.org_id = org_id
                request.state.role = role
                return await call_next(request)

        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
