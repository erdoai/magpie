"""Org and workspace management routes."""

import re

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-"))[:40]


class CreateOrgRequest(BaseModel):
    name: str
    slug: str | None = None


class InviteMemberRequest(BaseModel):
    email: str
    role: str = "member"


class CreateWorkspaceRequest(BaseModel):
    name: str
    slug: str | None = None


def _get_session_user_id(request: Request) -> str | None:
    """Get user_id from auth context (set by middleware)."""
    return getattr(request.state, "user_id", None)


# -- Orgs --


@router.post("/orgs")
async def create_org(body: CreateOrgRequest, request: Request):
    db = request.app.state.db
    user_id = _get_session_user_id(request)
    if not user_id:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    slug = body.slug or slugify(body.name)
    existing = await db.get_org_by_slug(slug)
    if existing:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=409, content={"error": "Org slug already taken"})

    org_id = await db.create_org(body.name, slug, user_id)
    org = await db.get_org(org_id)
    return org


@router.get("/orgs")
async def list_orgs(request: Request):
    db = request.app.state.db
    user_id = _get_session_user_id(request)
    if not user_id:
        return []
    return await db.list_user_orgs(user_id)


@router.get("/orgs/{org_id}/members")
async def list_members(org_id: str, request: Request):
    db = request.app.state.db
    return await db.list_org_members(org_id)


@router.post("/orgs/{org_id}/members")
async def invite_member(org_id: str, body: InviteMemberRequest, request: Request):
    db = request.app.state.db
    user = await db.get_or_create_user(body.email)
    await db.add_org_member(org_id, user["id"], body.role)
    return {"ok": True}


@router.delete("/orgs/{org_id}/members/{member_id}")
async def remove_member(org_id: str, member_id: str, request: Request):
    db = request.app.state.db
    ok = await db.remove_org_member(org_id, member_id)
    if not ok:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return {"ok": True}


# -- Workspaces --


@router.post("/orgs/{org_id}/workspaces")
async def create_workspace(org_id: str, body: CreateWorkspaceRequest, request: Request):
    db = request.app.state.db
    slug = body.slug or slugify(body.name)
    ws_id = await db.create_workspace(org_id, body.name, slug)
    return {"id": ws_id, "org_id": org_id, "name": body.name, "slug": slug}


@router.get("/orgs/{org_id}/workspaces")
async def list_workspaces(org_id: str, request: Request):
    db = request.app.state.db
    return await db.list_workspaces(org_id)


@router.delete("/workspaces/{ws_id}")
async def delete_workspace(ws_id: str, request: Request):
    db = request.app.state.db
    ok = await db.delete_workspace(ws_id)
    if not ok:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return {"ok": True}
