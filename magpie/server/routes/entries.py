"""Entry CRUD and search endpoints."""

import logging
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from magpie.links import normalize_target, sync_entry_links
from magpie.resolve import resolve_entry
from magpie.search.fusion import search
from magpie.server.context import AuthContext, auth_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "Not found"})


def _forbidden(message: str = "Forbidden") -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": message})


async def _get_accessible_entry(db, entry_id: str, ctx: AuthContext) -> dict | None:
    """Fetch an entry the caller is allowed to see. Inaccessible == not found."""
    # DB enforces visibility (fail-closed); can_access is belt-and-braces.
    entry = await db.get_entry(entry_id, **ctx.view_filter)
    if not entry or not ctx.can_access(entry):
        return None
    return entry


# -- Request/Response models --


class EntryCreate(BaseModel):
    title: str
    content: str
    tags: list[str] = []
    source: str | None = None
    workspace: str | None = None
    project: str | None = None
    dedupe: bool = False


class EntryUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    source: str | None = None


class SearchRequest(BaseModel):
    query: str
    tags: list[str] | None = None
    workspace: str | None = None
    project: str | None = None
    limit: int = 10
    semantic: bool = True
    keyword: bool = True


class EntryResponse(BaseModel):
    id: str
    title: str
    content: str
    tags: list[str]
    source: str | None
    user_id: str | None = None
    org_id: str | None = None
    workspace: str | None = None
    project: str | None = None
    archived_at: datetime | None = None
    score: float | None = None
    created_at: datetime
    updated_at: datetime


# -- Endpoints --


@router.post("/entries", response_model=EntryResponse)
async def create_entry(body: EntryCreate, request: Request):
    db = request.app.state.db
    embedder = request.app.state.embedder
    ctx = auth_context(request)

    if not ctx.has_role("editor"):
        return _forbidden("Write access requires editor role")

    workspace, project = ctx.clamp_scope(body.workspace, body.project)

    embedding = None
    if embedder:
        try:
            embedding = await embedder.embed(f"{body.title}\n{body.content}")
        except Exception:
            logger.exception("Failed to generate embedding, continuing without")

    if body.dedupe:
        entry_id, _was_updated = await db.upsert_entry(
            title=body.title,
            content=body.content,
            tags=body.tags,
            source=body.source,
            embedding=embedding,
            user_id=ctx.user_id,
            org_id=ctx.org_id,
            workspace=workspace,
            project=project,
        )
    else:
        entry_id = await db.create_entry(
            title=body.title,
            content=body.content,
            tags=body.tags,
            source=body.source,
            embedding=embedding,
            user_id=ctx.user_id,
            org_id=ctx.org_id,
            workspace=workspace,
            project=project,
        )

    await sync_entry_links(db, entry_id)
    entry = await db.get_entry(entry_id, trusted=True)  # just authored by caller
    return entry


@router.get("/entries", response_model=list[EntryResponse])
async def list_entries(
    request: Request,
    archived: bool | None = None,
    tags: str | None = None,
    source: str | None = None,
    workspace: str | None = None,
    project: str | None = None,
    offset: int = 0,
    limit: int = 50,
):
    db = request.app.state.db
    ctx = auth_context(request)
    workspace, project = ctx.clamp_scope(workspace, project)
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    return await db.list_entries(
        archived=archived,
        tags=tag_list,
        source=source,
        user_id=ctx.user_id,
        org_id=ctx.org_id,
        workspace=workspace,
        project=project,
        offset=offset,
        limit=limit,
    )


@router.get("/entries/{entry_id}", response_model=EntryResponse)
async def get_entry(entry_id: str, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)
    entry = await _get_accessible_entry(db, entry_id, ctx)
    if not entry:
        return _not_found()
    return entry


@router.get("/entries/{entry_id}/links")
async def get_entry_links(entry_id: str, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)
    entry = await _get_accessible_entry(db, entry_id, ctx)
    if not entry:
        return _not_found()
    outgoing = await db.get_outgoing_links(entry_id)
    backlinks = await db.get_backlinks(
        entry_id,
        normalize_target(entry["title"]),
        user_id=ctx.user_id,
        org_id=ctx.org_id,
    )
    return {"outgoing": outgoing, "backlinks": backlinks}


@router.post("/entries/{entry_id}/resolve")
async def resolve_entry_refs(entry_id: str, request: Request):
    """Render the entry's Markdown with [[wikilinks]], {{kv.paths}},
    and {{attachment:...}} references resolved. Returns the rendered
    markdown plus a dependency list with per-reference status."""
    db = request.app.state.db
    settings = request.app.state.settings
    ctx = auth_context(request)
    entry = await _get_accessible_entry(db, entry_id, ctx)
    if not entry:
        return _not_found()
    return await resolve_entry(db, entry, ctx, settings)


@router.put("/entries/{entry_id}", response_model=EntryResponse)
async def update_entry(entry_id: str, body: EntryUpdate, request: Request):
    db = request.app.state.db
    embedder = request.app.state.embedder
    ctx = auth_context(request)

    if not ctx.has_role("editor"):
        return _forbidden("Write access requires editor role")

    existing = await _get_accessible_entry(db, entry_id, ctx)
    if not existing:
        return _not_found()

    fields = body.model_dump(exclude_none=True)

    # Re-embed if content or title changed
    if embedder and ("content" in fields or "title" in fields):
        title = fields.get("title", existing["title"])
        content = fields.get("content", existing["content"])
        try:
            fields["embedding"] = await embedder.embed(f"{title}\n{content}")
        except Exception:
            logger.exception("Failed to re-embed, continuing without")

    ok = await db.update_entry(entry_id, **fields)
    if not ok:
        return _not_found()

    if "content" in fields:
        await sync_entry_links(db, entry_id)

    return await db.get_entry(entry_id, trusted=True)  # caller just updated it


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: str, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)

    if not ctx.has_role("editor"):
        return _forbidden("Write access requires editor role")

    if not await _get_accessible_entry(db, entry_id, ctx):
        return _not_found()

    # Delete attachment blobs before the rows cascade away
    storage = getattr(request.app.state, "storage", None)
    if storage:
        for att in await db.list_attachments(entry_id):
            try:
                await storage.delete(att["storage_key"])
            except Exception:
                logger.exception("Failed to delete blob %s", att["storage_key"])

    ok = await db.delete_entry(entry_id)
    if not ok:
        return _not_found()
    return {"ok": True}


@router.post("/entries/{entry_id}/archive")
async def archive_entry(entry_id: str, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)

    if not ctx.has_role("editor"):
        return _forbidden("Write access requires editor role")

    if not await _get_accessible_entry(db, entry_id, ctx):
        return _not_found()

    ok = await db.archive_entry(entry_id)
    if not ok:
        return _not_found()
    return {"ok": True}


@router.post("/entries/{entry_id}/unarchive")
async def unarchive_entry(entry_id: str, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)

    if not ctx.has_role("editor"):
        return _forbidden("Write access requires editor role")

    if not await _get_accessible_entry(db, entry_id, ctx):
        return _not_found()

    ok = await db.unarchive_entry(entry_id)
    if not ok:
        return _not_found()
    return {"ok": True}


class FindDuplicatesRequest(BaseModel):
    workspace: str | None = None
    project: str | None = None
    threshold: float = 0.12
    limit: int = 50


class MergeRequest(BaseModel):
    source_ids: list[str]
    title: str
    content: str
    tags: list[str] = []
    workspace: str | None = None
    project: str | None = None


@router.post("/entries/find-duplicates")
async def find_duplicates(body: FindDuplicatesRequest, request: Request):
    db = request.app.state.db
    ctx = auth_context(request)
    workspace, project = ctx.clamp_scope(body.workspace, body.project)
    clusters = await db.find_duplicate_clusters(
        workspace=workspace,
        project=project,
        user_id=ctx.user_id,
        org_id=ctx.org_id,
        threshold=body.threshold,
        limit=body.limit,
    )
    return {"clusters": clusters}


@router.post("/entries/merge", response_model=EntryResponse)
async def merge_entries(body: MergeRequest, request: Request):
    db = request.app.state.db
    embedder = request.app.state.embedder
    ctx = auth_context(request)

    if not ctx.has_role("editor"):
        return _forbidden("Write access requires editor role")

    if len(body.source_ids) < 2:
        return JSONResponse(
            status_code=400,
            content={"error": "Need at least 2 source entries to merge"},
        )

    # Every source entry must be visible to the caller
    for source_id in body.source_ids:
        if not await _get_accessible_entry(db, source_id, ctx):
            return _not_found()

    workspace, project = ctx.clamp_scope(body.workspace, body.project)

    embedding = None
    if embedder:
        try:
            embedding = await embedder.embed(f"{body.title}\n{body.content}")
        except Exception:
            logger.exception("Failed to generate embedding for merge")

    new_id = await db.merge_entries(
        source_ids=body.source_ids,
        title=body.title,
        content=body.content,
        tags=body.tags,
        embedding=embedding,
        user_id=ctx.user_id,
        org_id=ctx.org_id,
        workspace=workspace,
        project=project,
    )

    await sync_entry_links(db, new_id)
    entry = await db.get_entry(new_id, trusted=True)  # just created by caller
    return entry


@router.post("/search", response_model=list[EntryResponse])
async def search_entries(body: SearchRequest, request: Request):
    db = request.app.state.db
    embedder = request.app.state.embedder
    ctx = auth_context(request)
    workspace, project = ctx.clamp_scope(body.workspace, body.project)

    results = await search(
        db=db,
        query=body.query,
        embedder=embedder,
        user_id=ctx.user_id,
        org_id=ctx.org_id,
        workspace=workspace,
        project=project,
        tags=body.tags,
        limit=body.limit,
        semantic=body.semantic,
        keyword=body.keyword,
    )
    return results
