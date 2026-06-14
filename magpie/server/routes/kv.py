"""KV store and pair endpoints — named typed key->value stores."""

import logging
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from magpie.kv import VALUE_TYPES, validate_value
from magpie.manifest import normalize_slug
from magpie.server.context import AuthContext, auth_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "Not found"})


def _forbidden(message: str = "Forbidden") -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": message})


def _bad_request(message: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": message})


def _store_visible(store: dict, ctx: AuthContext) -> bool:
    # KV stores are org-scoped (or global); reuse entry visibility rules.
    return ctx.can_access({"user_id": None, "org_id": store.get("org_id")})


def _repo_locked(store: dict) -> JSONResponse | None:
    """Reject writes to repo-canonical stores — the bundle is the source
    of truth, so they're edited in the repo and synced with `magpie push`."""
    if store.get("source") == "repo":
        return _forbidden(
            "KV store is repo-canonical; edit the bundle file and run "
            "`magpie push` (server writes are rejected to prevent drift)"
        )
    return None


async def _find_visible_store(
    db, slug: str, ctx: AuthContext, workspace: str | None, project: str | None
) -> dict | None:
    workspace, project = ctx.clamp_scope(workspace, project)
    store = await db.find_kv_store(
        slug, org_id=ctx.org_id, workspace=workspace, project=project
    )
    if not store or not _store_visible(store, ctx):
        return None
    return store


class KvStoreCreate(BaseModel):
    slug: str
    title: str
    description: str | None = None
    workspace: str | None = None
    project: str | None = None
    visibility: str = "org"


class KvPairSet(BaseModel):
    value: Any
    value_type: str = "json"
    summary: str | None = None


# -- KV stores --


@router.post("/kv")
async def create_kv_store(body: KvStoreCreate, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)

    if not ctx.has_role("editor"):
        return _forbidden("Write access requires editor role")

    if not SLUG_RE.match(body.slug):
        return _bad_request(
            "Invalid slug: lowercase letters, digits, dots, dashes, underscores"
        )

    workspace, project = ctx.clamp_scope(body.workspace, body.project)

    existing = await db.find_kv_store(
        body.slug, org_id=ctx.org_id, workspace=workspace, project=project
    )
    if existing and existing.get("org_id") == ctx.org_id:
        return JSONResponse(
            status_code=409, content={"error": "KV store slug already exists"}
        )

    # Anti-drift: refuse a slug that near-duplicates an existing store in scope
    # (e.g. "reach_strategy" when "reach-strategy" exists).
    norm = normalize_slug(body.slug)
    siblings = await db.list_kv_stores(
        org_id=ctx.org_id, workspace=workspace, project=project
    )
    dup = next(
        (s for s in siblings
         if s["slug"] != body.slug and normalize_slug(s["slug"]) == norm),
        None,
    )
    if dup:
        return _bad_request(
            f"Near-duplicate of existing KV store '{dup['slug']}'. "
            "Use that slug, or pick a clearly distinct name."
        )

    store_id = await db.create_kv_store(
        slug=body.slug,
        title=body.title,
        description=body.description,
        visibility=body.visibility,
        org_id=ctx.org_id,
        workspace=workspace,
        project=project,
        created_by_user_id=ctx.user_id,
    )
    return await db.get_kv_store(store_id, trusted=True)  # just created by caller


@router.get("/kv")
async def list_kv_stores(
    request: Request,
    workspace: str | None = None,
    project: str | None = None,
):
    db = request.app.state.db
    ctx = auth_context(request)
    workspace, project = ctx.clamp_scope(workspace, project)
    stores = await db.list_kv_stores(
        org_id=ctx.org_id, workspace=workspace, project=project
    )
    return [s for s in stores if _store_visible(s, ctx)]


@router.delete("/kv/{store_id}")
async def delete_kv_store(store_id: str, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)

    if not ctx.has_role("editor"):
        return _forbidden("Write access requires editor role")

    store = await db.get_kv_store(store_id, **ctx.view_filter)
    if not store or not _store_visible(store, ctx):
        return _not_found()

    await db.delete_kv_store(store_id)
    return {"ok": True}


# -- KV pairs --


@router.get("/kv/{slug}/keys")
async def list_kv_pairs(
    slug: str,
    request: Request,
    workspace: str | None = None,
    project: str | None = None,
):
    db = request.app.state.db
    ctx = auth_context(request)
    store = await _find_visible_store(db, slug, ctx, workspace, project)
    if not store:
        return _not_found()
    pairs = await db.list_kv_pairs(store["id"])
    return {"store": store, "pairs": pairs}


@router.get("/kv/{slug}/keys/{key}")
async def get_kv_pair(
    slug: str,
    key: str,
    request: Request,
    workspace: str | None = None,
    project: str | None = None,
):
    db = request.app.state.db
    ctx = auth_context(request)
    store = await _find_visible_store(db, slug, ctx, workspace, project)
    if not store:
        return _not_found()
    pair = await db.get_kv_pair(store["id"], key, **ctx.view_filter)
    if not pair:
        return _not_found()
    return pair


@router.put("/kv/{slug}/keys/{key}")
async def set_kv_pair(
    slug: str,
    key: str,
    body: KvPairSet,
    request: Request,
    workspace: str | None = None,
    project: str | None = None,
):
    db = request.app.state.db
    ctx = auth_context(request)

    if not ctx.has_role("editor"):
        return _forbidden("Write access requires editor role")

    if body.value_type not in VALUE_TYPES:
        return _bad_request(
            f"Unknown value_type '{body.value_type}'. One of: {', '.join(VALUE_TYPES)}"
        )

    error = validate_value(body.value, body.value_type)
    if error:
        return _bad_request(error)

    store = await _find_visible_store(db, slug, ctx, workspace, project)
    if not store:
        return _not_found()
    locked = _repo_locked(store)
    if locked:
        return locked

    await db.set_kv_pair(
        store_id=store["id"],
        key=key,
        value=body.value,
        value_type=body.value_type,
        summary=body.summary,
        org_id=store.get("org_id"),
        created_by_user_id=ctx.user_id,
    )
    return await db.get_kv_pair(store["id"], key, trusted=True)  # just written by caller


@router.delete("/kv/{slug}/keys/{key}")
async def delete_kv_pair(
    slug: str,
    key: str,
    request: Request,
    workspace: str | None = None,
    project: str | None = None,
):
    db = request.app.state.db
    ctx = auth_context(request)

    if not ctx.has_role("editor"):
        return _forbidden("Write access requires editor role")

    store = await _find_visible_store(db, slug, ctx, workspace, project)
    if not store:
        return _not_found()
    locked = _repo_locked(store)
    if locked:
        return locked

    ok = await db.delete_kv_pair(store["id"], key)
    if not ok:
        return _not_found()
    return {"ok": True}
