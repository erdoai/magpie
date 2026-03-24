"""API key management endpoints."""

import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

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
    user_id: str | None = None
    org_id: str | None = None


class KeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    user_id: str | None
    org_id: str | None
    created_at: datetime
    last_used_at: datetime | None


class KeyCreateResponse(KeyResponse):
    key: str  # Only returned on creation


@router.post("/keys", response_model=KeyCreateResponse)
async def create_key(body: KeyCreate, request: Request):
    db = request.app.state.db
    full_key, key_hash, key_prefix = generate_api_key()
    key_id = await db.create_api_key(
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        user_id=body.user_id,
        org_id=body.org_id,
    )
    record = await db.get_api_key(key_id)
    return {**record, "key": full_key}


@router.get("/keys", response_model=list[KeyResponse])
async def list_keys(request: Request):
    db = request.app.state.db
    return await db.list_api_keys()


@router.delete("/keys/{key_id}")
async def delete_key(key_id: str, request: Request):
    db = request.app.state.db
    ok = await db.delete_api_key(key_id)
    if not ok:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return {"ok": True}
