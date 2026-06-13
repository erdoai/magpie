"""Org and workspace management routes."""

import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from magpie.server.context import ROLE_LEVELS, auth_context

router = APIRouter(prefix="/api")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-"))[:40]


class CreateOrgRequest(BaseModel):
    name: str
    slug: str | None = None


class InviteMemberRequest(BaseModel):
    email: str
    role: str = "editor"


class CreateWorkspaceRequest(BaseModel):
    name: str
    slug: str | None = None


def _unauthorized() -> JSONResponse:
    return JSONResponse(status_code=401, content={"error": "Not authenticated"})


def _forbidden(message: str = "Forbidden") -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": message})


async def _require_org_role(request: Request, org_id: str, minimum: str):
    """Return None if the caller has at least `minimum` role in the org,
    else an error response."""
    ctx = auth_context(request)
    if ctx.is_unrestricted:
        return None
    if not ctx.user_id:
        return _unauthorized()
    db = request.app.state.db
    role = await db.get_org_role(org_id, ctx.user_id)
    if role is None:
        # Not a member — don't reveal the org exists
        return JSONResponse(status_code=404, content={"error": "Not found"})
    if ROLE_LEVELS.get(role, 0) < ROLE_LEVELS[minimum]:
        return _forbidden(f"Requires {minimum} role")
    return None


# -- Orgs --


@router.post("/orgs")
async def create_org(body: CreateOrgRequest, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)
    if not ctx.user_id:
        return _unauthorized()

    slug = body.slug or slugify(body.name)
    existing = await db.get_org_by_slug(slug)
    if existing:
        return JSONResponse(status_code=409, content={"error": "Org slug already taken"})

    org_id = await db.create_org(body.name, slug, ctx.user_id)
    org = await db.get_org(org_id)
    return org


@router.get("/orgs")
async def list_orgs(request: Request):
    db = request.app.state.db
    ctx = auth_context(request)
    if not ctx.user_id:
        return []
    return await db.list_user_orgs(ctx.user_id)


@router.post("/orgs/{org_id}/select")
async def select_org(org_id: str, request: Request):
    """Persist this org as the caller's default active org (used when no
    X-Organization-ID header is sent, e.g. cookie sessions). Membership-checked."""
    ctx = auth_context(request)
    if not ctx.user_id:
        return _unauthorized()
    db = request.app.state.db
    role = await db.get_org_role(org_id, ctx.user_id)
    if role is None:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    await db.set_user_default_org(ctx.user_id, org_id)
    return {"ok": True, "org_id": org_id, "role": role}


@router.get("/orgs/{org_id}/members")
async def list_members(org_id: str, request: Request):
    err = await _require_org_role(request, org_id, "viewer")
    if err:
        return err
    db = request.app.state.db
    return await db.list_org_members(org_id)


@router.post("/orgs/{org_id}/members")
async def invite_member(org_id: str, body: InviteMemberRequest, request: Request):
    err = await _require_org_role(request, org_id, "admin")
    if err:
        return err
    if body.role not in ROLE_LEVELS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid role. One of: {', '.join(ROLE_LEVELS)}"},
        )
    db = request.app.state.db
    user = await db.get_or_create_user(body.email)
    await db.add_org_member(org_id, user["id"], body.role)
    return {"ok": True}


@router.delete("/orgs/{org_id}/members/{member_id}")
async def remove_member(org_id: str, member_id: str, request: Request):
    ctx = auth_context(request)
    # Members may remove themselves; otherwise admin required
    if not (ctx.user_id and ctx.user_id == member_id):
        err = await _require_org_role(request, org_id, "admin")
        if err:
            return err
    db = request.app.state.db
    ok = await db.remove_org_member(org_id, member_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return {"ok": True}


# -- Workspaces --


@router.post("/orgs/{org_id}/workspaces")
async def create_workspace(org_id: str, body: CreateWorkspaceRequest, request: Request):
    err = await _require_org_role(request, org_id, "editor")
    if err:
        return err
    db = request.app.state.db
    slug = body.slug or slugify(body.name)
    ws_id = await db.create_workspace(org_id, body.name, slug)
    return {"id": ws_id, "org_id": org_id, "name": body.name, "slug": slug}


@router.get("/orgs/{org_id}/workspaces")
async def list_workspaces(org_id: str, request: Request):
    err = await _require_org_role(request, org_id, "viewer")
    if err:
        return err
    db = request.app.state.db
    return await db.list_workspaces(org_id)


@router.delete("/workspaces/{ws_id}")
async def delete_workspace(ws_id: str, request: Request):
    db = request.app.state.db
    ws = await db.get_workspace(ws_id)
    if not ws:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    err = await _require_org_role(request, ws["org_id"], "admin")
    if err:
        return err
    ok = await db.delete_workspace(ws_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return {"ok": True}
