"""Collection and document endpoints — named JSON document stores."""

import logging
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from magpie.collections import VALUE_TYPES, validate_value
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


def _collection_visible(col: dict, ctx: AuthContext) -> bool:
    # Collections are org-scoped (or global); reuse entry visibility rules.
    return ctx.can_access({"user_id": None, "org_id": col.get("org_id")})


def _repo_locked(col: dict) -> JSONResponse | None:
    """Reject writes to repo-canonical collections — the bundle is the source
    of truth, so they're edited in the repo and synced with `magpie push`."""
    if col.get("source") == "repo":
        return _forbidden(
            "Collection is repo-canonical; edit the bundle file and run "
            "`magpie push` (server writes are rejected to prevent drift)"
        )
    return None


async def _find_visible_collection(
    db, slug: str, ctx: AuthContext, workspace: str | None, project: str | None
) -> dict | None:
    workspace, project = ctx.clamp_scope(workspace, project)
    col = await db.find_collection(
        slug, org_id=ctx.org_id, workspace=workspace, project=project
    )
    if not col or not _collection_visible(col, ctx):
        return None
    return col


class CollectionCreate(BaseModel):
    slug: str
    title: str
    description: str | None = None
    workspace: str | None = None
    project: str | None = None
    visibility: str = "org"


class DocumentSet(BaseModel):
    value: Any
    value_type: str = "json"
    summary: str | None = None


# -- Collections --


@router.post("/collections")
async def create_collection(body: CollectionCreate, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)

    if not ctx.has_role("editor"):
        return _forbidden("Write access requires editor role")

    if not SLUG_RE.match(body.slug):
        return _bad_request(
            "Invalid slug: lowercase letters, digits, dots, dashes, underscores"
        )

    workspace, project = ctx.clamp_scope(body.workspace, body.project)

    existing = await db.find_collection(
        body.slug, org_id=ctx.org_id, workspace=workspace, project=project
    )
    if existing and existing.get("org_id") == ctx.org_id:
        return JSONResponse(
            status_code=409, content={"error": "Collection slug already exists"}
        )

    col_id = await db.create_collection(
        slug=body.slug,
        title=body.title,
        description=body.description,
        visibility=body.visibility,
        org_id=ctx.org_id,
        workspace=workspace,
        project=project,
        created_by_user_id=ctx.user_id,
    )
    return await db.get_collection(col_id)


@router.get("/collections")
async def list_collections(
    request: Request,
    workspace: str | None = None,
    project: str | None = None,
):
    db = request.app.state.db
    ctx = auth_context(request)
    workspace, project = ctx.clamp_scope(workspace, project)
    collections = await db.list_collections(
        org_id=ctx.org_id, workspace=workspace, project=project
    )
    return [c for c in collections if _collection_visible(c, ctx)]


@router.delete("/collections/{col_id}")
async def delete_collection(col_id: str, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)

    if not ctx.has_role("editor"):
        return _forbidden("Write access requires editor role")

    col = await db.get_collection(col_id)
    if not col or not _collection_visible(col, ctx):
        return _not_found()

    await db.delete_collection(col_id)
    return {"ok": True}


# -- Documents --


@router.get("/collections/{slug}/documents")
async def list_documents(
    slug: str,
    request: Request,
    workspace: str | None = None,
    project: str | None = None,
):
    db = request.app.state.db
    ctx = auth_context(request)
    col = await _find_visible_collection(db, slug, ctx, workspace, project)
    if not col:
        return _not_found()
    documents = await db.list_documents(col["id"])
    return {"collection": col, "documents": documents}


@router.get("/collections/{slug}/documents/{key}")
async def get_document(
    slug: str,
    key: str,
    request: Request,
    workspace: str | None = None,
    project: str | None = None,
):
    db = request.app.state.db
    ctx = auth_context(request)
    col = await _find_visible_collection(db, slug, ctx, workspace, project)
    if not col:
        return _not_found()
    doc = await db.get_document(col["id"], key)
    if not doc:
        return _not_found()
    return doc


@router.put("/collections/{slug}/documents/{key}")
async def set_document(
    slug: str,
    key: str,
    body: DocumentSet,
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

    col = await _find_visible_collection(db, slug, ctx, workspace, project)
    if not col:
        return _not_found()
    locked = _repo_locked(col)
    if locked:
        return locked

    await db.set_document(
        collection_id=col["id"],
        key=key,
        value=body.value,
        value_type=body.value_type,
        summary=body.summary,
        org_id=col.get("org_id"),
        created_by_user_id=ctx.user_id,
    )
    return await db.get_document(col["id"], key)


@router.delete("/collections/{slug}/documents/{key}")
async def delete_document(
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

    col = await _find_visible_collection(db, slug, ctx, workspace, project)
    if not col:
        return _not_found()
    locked = _repo_locked(col)
    if locked:
        return locked

    ok = await db.delete_document(col["id"], key)
    if not ok:
        return _not_found()
    return {"ok": True}
