"""Entry CRUD and search endpoints."""

import logging
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from magpie.search.fusion import search

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# -- Request/Response models --


class EntryCreate(BaseModel):
    title: str
    content: str
    category: str = "resource"
    tags: list[str] = []
    source: str | None = None
    user_id: str | None = None
    project_id: str | None = None


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
    user_id: str | None = None
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
    score: float | None = None
    created_at: datetime
    updated_at: datetime


# -- Endpoints --


@router.post("/entries", response_model=EntryResponse)
async def create_entry(body: EntryCreate, request: Request):
    db = request.app.state.db
    embedder = request.app.state.embedder

    embedding = None
    if embedder:
        try:
            embedding = await embedder.embed(f"{body.title}\n{body.content}")
        except Exception:
            logger.exception("Failed to generate embedding, continuing without")

    entry_id = await db.create_entry(
        title=body.title,
        content=body.content,
        category=body.category,
        tags=body.tags,
        source=body.source,
        embedding=embedding,
        user_id=body.user_id,
        project_id=body.project_id,
    )

    entry = await db.get_entry(entry_id)
    return entry


@router.get("/entries", response_model=list[EntryResponse])
async def list_entries(
    request: Request,
    category: str | None = None,
    tags: str | None = None,
    source: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    offset: int = 0,
    limit: int = 50,
):
    db = request.app.state.db
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    return await db.list_entries(
        category=category,
        tags=tag_list,
        source=source,
        user_id=user_id,
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


@router.post("/search", response_model=list[EntryResponse])
async def search_entries(body: SearchRequest, request: Request):
    db = request.app.state.db
    embedder = request.app.state.embedder

    results = await search(
        db=db,
        query=body.query,
        embedder=embedder,
        user_id=body.user_id,
        category=body.category,
        tags=body.tags,
        limit=body.limit,
        semantic=body.semantic,
        keyword=body.keyword,
    )
    return results
