"""API key management endpoints."""

import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from magpie.server.context import ROLE_LEVELS, auth_context

router = APIRouter(prefix="/api")


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key. Returns (full_key, key_hash, key_prefix)."""
    raw = secrets.token_urlsafe(32)
    full_key = f"mgp_{raw}"
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    key_prefix = full_key[:12]
    return full_key, key_hash, key_prefix


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class KeyCreate(BaseModel):
    name: str
    workspace: str | None = None
    project: str | None = None
    role: str = "editor"


class KeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    user_id: str | None
    org_id: str | None
    workspace: str | None = None
    project: str | None = None
    role: str = "editor"
    created_at: datetime
    last_used_at: datetime | None


class KeyCreateResponse(KeyResponse):
    key: str  # Only returned on creation


@router.post("/keys", response_model=KeyCreateResponse)
async def create_key(body: KeyCreate, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)

    if body.role not in ROLE_LEVELS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid role. One of: {', '.join(ROLE_LEVELS)}"},
        )

    # A key can never grant more than the caller has
    if not ctx.is_unrestricted:
        caller_level = ROLE_LEVELS.get(ctx.role or "editor", 0)
        if ROLE_LEVELS[body.role] > caller_level:
            return JSONResponse(
                status_code=403,
                content={"error": "Cannot create a key with a higher role than your own"},
            )

    full_key, key_hash, key_prefix = generate_api_key()
    key_id = await db.create_api_key(
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        user_id=ctx.user_id,
        org_id=ctx.org_id,
        workspace=body.workspace,
        project=body.project,
        role=body.role,
    )
    record = await db.get_api_key(key_id)
    return {**record, "key": full_key}


@router.get("/keys", response_model=list[KeyResponse])
async def list_keys(request: Request):
    db = request.app.state.db
    ctx = auth_context(request)
    if ctx.is_unrestricted:
        return await db.list_api_keys()
    if not ctx.user_id:
        return []
    return await db.list_api_keys_for_user(ctx.user_id)


@router.delete("/keys/{key_id}")
async def delete_key(key_id: str, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)

    record = await db.get_api_key(key_id)
    if not record:
        return JSONResponse(status_code=404, content={"error": "Not found"})

    if not ctx.is_unrestricted and record.get("user_id") != ctx.user_id:
        return JSONResponse(status_code=404, content={"error": "Not found"})

    ok = await db.delete_api_key(key_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return {"ok": True}
