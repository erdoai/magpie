"""Attachment endpoints — upload, read, download, delete, public assets."""

import logging
from uuid import uuid4

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response

from magpie.attachments import (
    attachment_payload,
    infer_kind,
    is_browser_safe,
    storage_key_for,
)
from magpie.server.context import AuthContext, auth_context

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "Not found"})


def _forbidden(message: str = "Forbidden") -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": message})


async def _accessible_attachment(db, att_id: str, ctx: AuthContext) -> dict | None:
    """An attachment is visible iff its owning entry is."""
    att = await db.get_attachment(att_id)
    if not att:
        return None
    entry = await db.get_entry(att["entry_id"])
    if not entry or not ctx.can_access(entry):
        return None
    return att


@router.post("/api/entries/{entry_id}/attachments")
async def upload_attachment(
    entry_id: str,
    request: Request,
    file: UploadFile = File(...),
    description: str | None = Form(None),
    role: str | None = Form(None),
    public: bool = Form(False),
):
    db = request.app.state.db
    storage = request.app.state.storage
    settings = request.app.state.settings
    ctx = auth_context(request)

    if not storage:
        return JSONResponse(
            status_code=503, content={"error": "Attachment storage not configured"}
        )
    if not ctx.has_role("editor"):
        return _forbidden("Write access requires editor role")

    entry = await db.get_entry(entry_id)
    if not entry or not ctx.can_access(entry):
        return _not_found()

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse(status_code=413, content={"error": "File too large (max 50MB)"})
    if not data:
        return JSONResponse(status_code=400, content={"error": "Empty file"})

    filename = file.filename or "file"
    media_type = file.content_type or "application/octet-stream"
    kind = infer_kind(filename, media_type)

    if public and not is_browser_safe(media_type):
        return JSONResponse(
            status_code=400,
            content={"error": "Only browser-safe image media can be public"},
        )

    att_id = uuid4().hex
    storage_key = storage_key_for(entry.get("org_id"), entry_id, att_id, filename)
    await storage.put(storage_key, data, media_type)

    await db.create_attachment(
        att_id=att_id,
        entry_id=entry_id,
        kind=kind,
        filename=filename,
        media_type=media_type,
        storage_key=storage_key,
        byte_size=len(data),
        org_id=entry.get("org_id"),
        description=description,
        role=role,
        public=public,
        created_by_user_id=ctx.user_id,
    )

    att = await db.get_attachment(att_id)
    return await attachment_payload(att, storage, settings)


@router.get("/api/entries/{entry_id}/attachments")
async def list_attachments(entry_id: str, request: Request):
    db = request.app.state.db
    storage = request.app.state.storage
    settings = request.app.state.settings
    ctx = auth_context(request)

    entry = await db.get_entry(entry_id)
    if not entry or not ctx.can_access(entry):
        return _not_found()

    attachments = await db.list_attachments(entry_id)
    return [
        await attachment_payload(att, storage, settings, include_content=False)
        for att in attachments
    ]


@router.get("/api/attachments/{att_id}")
async def get_attachment(att_id: str, request: Request):
    db = request.app.state.db
    storage = request.app.state.storage
    settings = request.app.state.settings
    ctx = auth_context(request)

    att = await _accessible_attachment(db, att_id, ctx)
    if not att:
        return _not_found()
    return await attachment_payload(att, storage, settings)


@router.get("/api/attachments/{att_id}/download")
async def download_attachment(att_id: str, request: Request):
    db = request.app.state.db
    storage = request.app.state.storage
    ctx = auth_context(request)

    att = await _accessible_attachment(db, att_id, ctx)
    if not att or not storage:
        return _not_found()

    signed = await storage.signed_url(att["storage_key"])
    if signed:
        return RedirectResponse(url=signed, status_code=307)

    data = await storage.get(att["storage_key"])
    if data is None:
        return _not_found()
    return Response(
        content=data,
        media_type=att["media_type"],
        headers={
            "Content-Disposition": f'inline; filename="{att["filename"]}"',
            "Cache-Control": "private, max-age=300",
        },
    )


@router.delete("/api/attachments/{att_id}")
async def delete_attachment(att_id: str, request: Request):
    db = request.app.state.db
    storage = request.app.state.storage
    ctx = auth_context(request)

    if not ctx.has_role("editor"):
        return _forbidden("Write access requires editor role")

    att = await _accessible_attachment(db, att_id, ctx)
    if not att:
        return _not_found()

    if storage:
        try:
            await storage.delete(att["storage_key"])
        except Exception:
            logger.exception("Failed to delete attachment blob %s", att["storage_key"])

    await db.delete_attachment(att_id)
    return {"ok": True}


@router.get("/public/assets/{att_id}")
async def public_asset(att_id: str, request: Request):
    """Unauthenticated, stable URL for explicitly public browser-safe media.

    Never serves SQL/text/PDF/document attachments.
    """
    db = request.app.state.db
    storage = request.app.state.storage

    att = await db.get_attachment(att_id)
    if (
        not att
        or not att.get("public")
        or not is_browser_safe(att["media_type"])
        or not storage
    ):
        return _not_found()

    data = await storage.get(att["storage_key"])
    if data is None:
        return _not_found()
    return Response(
        content=data,
        media_type=att["media_type"],
        headers={
            "Content-Disposition": f'inline; filename="{att["filename"]}"',
            "Cache-Control": "public, max-age=86400",
        },
    )
