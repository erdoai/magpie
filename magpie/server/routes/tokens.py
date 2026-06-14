"""Access token management endpoints."""

import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from magpie.server.context import ROLE_LEVELS, auth_context

router = APIRouter(prefix="/api")


def generate_token() -> tuple[str, str, str]:
    """Generate a new access token. Returns (full_token, token_hash, token_prefix)."""
    raw = secrets.token_urlsafe(32)
    full_token = f"mgp_{raw}"
    token_hash = hashlib.sha256(full_token.encode()).hexdigest()
    token_prefix = full_token[:12]
    return full_token, token_hash, token_prefix


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenCreate(BaseModel):
    name: str
    workspace: str | None = None
    project: str | None = None
    role: str = "editor"


class TokenResponse(BaseModel):
    id: str
    name: str
    token_prefix: str
    user_id: str | None
    org_id: str | None
    workspace: str | None = None
    project: str | None = None
    role: str = "editor"
    created_at: datetime
    last_used_at: datetime | None


class TokenCreateResponse(TokenResponse):
    token: str  # Only returned on creation


@router.post("/tokens", response_model=TokenCreateResponse)
async def create_token(body: TokenCreate, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)

    if body.role not in ROLE_LEVELS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid role. One of: {', '.join(ROLE_LEVELS)}"},
        )

    # A token can never grant more than the caller has
    if not ctx.is_unrestricted:
        caller_level = ROLE_LEVELS.get(ctx.role or "editor", 0)
        if ROLE_LEVELS[body.role] > caller_level:
            return JSONResponse(
                status_code=403,
                content={"error": "Cannot create a token with a higher role than your own"},
            )

    full_token, token_hash, token_prefix = generate_token()
    token_id = await db.create_token(
        name=body.name,
        token_hash=token_hash,
        token_prefix=token_prefix,
        user_id=ctx.user_id,
        org_id=ctx.org_id,
        workspace=body.workspace,
        project=body.project,
        role=body.role,
    )
    record = await db.get_token(token_id)
    return {**record, "token": full_token}


@router.get("/tokens", response_model=list[TokenResponse])
async def list_tokens(request: Request):
    db = request.app.state.db
    ctx = auth_context(request)
    if ctx.is_unrestricted:
        return await db.list_tokens()
    if not ctx.user_id:
        return []
    return await db.list_tokens_for_user(ctx.user_id)


@router.delete("/tokens/{token_id}")
async def delete_token(token_id: str, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)

    record = await db.get_token(token_id)
    if not record:
        return JSONResponse(status_code=404, content={"error": "Not found"})

    if not ctx.is_unrestricted and record.get("user_id") != ctx.user_id:
        return JSONResponse(status_code=404, content={"error": "Not found"})

    ok = await db.delete_token(token_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return {"ok": True}
