"""Entry CRUD and search endpoints."""

import logging
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from magpie.search.fusion import search

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _auth_context(request: Request) -> dict:
    """Get user_id and org_id from auth middleware."""
    return {
        "user_id": getattr(request.state, "user_id", None),
        "org_id": getattr(request.state, "org_id", None),
    }


# -- Request/Response models --


class EntryCreate(BaseModel):
    title: str
    content: str
    category: str = "resource"
    tags: list[str] = []
    source: str | None = None
    workspace: str | None = None
    dedupe: bool = False


class EntryUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    source: str | None = None


class SearchRequest(BaseModel):
    query: str
    category: str | None = None
    tags: list[str] | None = None
    workspace: str | None = None
    limit: int = 10
    semantic: bool = True
    keyword: bool = True


class EntryResponse(BaseModel):
    id: str
    title: str
    content: str
    category: str
    tags: list[str]
    source: str | None
    user_id: str | None = None
    project_id: str | None = None
    org_id: str | None = None
    workspace: str | None = None
    score: float | None = None
    created_at: datetime
    updated_at: datetime


# -- Endpoints --


@router.post("/entries", response_model=EntryResponse)
async def create_entry(body: EntryCreate, request: Request):
    db = request.app.state.db
    embedder = request.app.state.embedder
    ctx = _auth_context(request)

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
            category=body.category,
            tags=body.tags,
            source=body.source,
            embedding=embedding,
            user_id=ctx["user_id"],
            org_id=ctx["org_id"],
            workspace=body.workspace,
        )
    else:
        entry_id = await db.create_entry(
            title=body.title,
            content=body.content,
            category=body.category,
            tags=body.tags,
            source=body.source,
            embedding=embedding,
            user_id=ctx["user_id"],
            org_id=ctx["org_id"],
            workspace=body.workspace,
        )

    entry = await db.get_entry(entry_id)
    return entry


@router.get("/entries", response_model=list[EntryResponse])
async def list_entries(
    request: Request,
    category: str | None = None,
    tags: str | None = None,
    source: str | None = None,
    workspace: str | None = None,
    project_id: str | None = None,
    offset: int = 0,
    limit: int = 50,
):
    db = request.app.state.db
    ctx = _auth_context(request)
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    return await db.list_entries(
        category=category,
        tags=tag_list,
        source=source,
        user_id=ctx["user_id"],
        org_id=ctx["org_id"],
        workspace=workspace,
        project_id=project_id,
        offset=offset,
        limit=limit,
    )


@router.get("/entries/{entry_id}", response_model=EntryResponse)
async def get_entry(entry_id: str, request: Request):
    db = request.app.state.db
    entry = await db.get_entry(entry_id)
    if not entry:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"error": "Not found"})
    return entry


@router.put("/entries/{entry_id}", response_model=EntryResponse)
async def update_entry(entry_id: str, body: EntryUpdate, request: Request):
    db = request.app.state.db
    embedder = request.app.state.embedder

    fields = body.model_dump(exclude_none=True)

    # Re-embed if content or title changed
    if embedder and ("content" in fields or "title" in fields):
        existing = await db.get_entry(entry_id)
        if existing:
            title = fields.get("title", existing["title"])
            content = fields.get("content", existing["content"])
            try:
                fields["embedding"] = await embedder.embed(f"{title}\n{content}")
            except Exception:
                logger.exception("Failed to re-embed, continuing without")

    ok = await db.update_entry(entry_id, **fields)
    if not ok:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"error": "Not found"})

    return await db.get_entry(entry_id)


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: str, request: Request):
    db = request.app.state.db
    ok = await db.delete_entry(entry_id)
    if not ok:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"error": "Not found"})
    return {"ok": True}


@router.post("/entries/{entry_id}/archive")
async def archive_entry(entry_id: str, request: Request):
    db = request.app.state.db
    ok = await db.archive_entry(entry_id)
    if not ok:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"error": "Not found"})
    return {"ok": True}


class FindDuplicatesRequest(BaseModel):
    workspace: str | None = None
    threshold: float = 0.12
    limit: int = 50


class MergeRequest(BaseModel):
    source_ids: list[str]
    title: str
    content: str
    category: str = "resource"
    tags: list[str] = []
    workspace: str | None = None


@router.post("/entries/find-duplicates")
async def find_duplicates(body: FindDuplicatesRequest, request: Request):
    db = request.app.state.db
    ctx = _auth_context(request)
    clusters = await db.find_duplicate_clusters(
        workspace=body.workspace,
        user_id=ctx["user_id"],
        org_id=ctx["org_id"],
        threshold=body.threshold,
        limit=body.limit,
    )
    return {"clusters": clusters}


@router.post("/entries/merge", response_model=EntryResponse)
async def merge_entries(body: MergeRequest, request: Request):
    db = request.app.state.db
    embedder = request.app.state.embedder
    ctx = _auth_context(request)

    if len(body.source_ids) < 2:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=400,
            content={"error": "Need at least 2 source entries to merge"},
        )

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
        category=body.category,
        tags=body.tags,
        embedding=embedding,
        user_id=ctx["user_id"],
        org_id=ctx["org_id"],
        workspace=body.workspace,
    )

    entry = await db.get_entry(new_id)
    return entry


@router.post("/search", response_model=list[EntryResponse])
async def search_entries(body: SearchRequest, request: Request):
    db = request.app.state.db
    embedder = request.app.state.embedder
    ctx = _auth_context(request)

    results = await search(
        db=db,
        query=body.query,
        embedder=embedder,
        user_id=ctx["user_id"],
        org_id=ctx["org_id"],
        category=body.category,
        tags=body.tags,
        limit=body.limit,
        semantic=body.semantic,
        keyword=body.keyword,
    )
    return results
