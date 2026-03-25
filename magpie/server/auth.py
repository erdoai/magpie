"""Bearer token auth — supports static key + per-user API keys."""

import hashlib
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        static_key = request.app.state.settings.api_key

        # No auth configured — allow all
        if not static_key:
            return await call_next(request)

        # Public paths — no auth needed
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Static assets and SPA HTML — no auth needed (the app itself is public,
        # but all data access requires auth via API/MCP)
        if request.url.path.startswith("/assets") or (
            not request.url.path.startswith("/api")
            and not request.url.path.startswith("/mcp")
        ):
            return await call_next(request)

        # Everything below requires auth: /api/* and /mcp/*
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        token = auth_header[7:]

        # 1. Check static API key
        if token == static_key:
            request.state.user_id = None
            request.state.org_id = None
            return await call_next(request)

        # 2. Check per-user API keys in DB
        db = request.app.state.db
        key_record = await db.get_api_key_by_hash(hash_key(token))
        if key_record:
            await db.touch_api_key(key_record["id"])
            request.state.user_id = key_record.get("user_id")
            request.state.org_id = key_record.get("org_id")
            return await call_next(request)

        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
