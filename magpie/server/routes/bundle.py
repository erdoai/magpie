"""Bundle push/export endpoints — repo sync for the TypeScript CLI.

Thin HTTP wrappers over the shared sync logic: the client sends raw bundle file
contents (or asks for them), and the server does all parsing, validation,
anti-drift, and upsert via :mod:`magpie.bundle`, :mod:`magpie.manifest`,
:mod:`magpie.sync`, and :mod:`magpie.export` — the same code the Python CLI
runs. Clients stay thin (file I/O + HTTP); logic lives here, once.
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from magpie.bundle import parse_collection_items, parse_entry_items
from magpie.export import render_bundle
from magpie.manifest import check_drift
from magpie.server.context import auth_context
from magpie.sync import apply_push, gather_export

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bundle")


class EntryFile(BaseModel):
    path: str
    text: str


class CollectionFile(BaseModel):
    slug: str
    text: str


class PushRequest(BaseModel):
    entries: list[EntryFile] = []
    collections: list[CollectionFile] = []
    manifest: dict | None = None
    workspace: str | None = None
    project: str | None = None


@router.post("/push")
async def push_bundle(body: PushRequest, request: Request):
    """Validate and apply a bundle. Mirrors `magpie push` exactly.

    Aborts (422) without writing if any file is off-spec or any drift/conflict
    is found, reporting every problem at once.
    """
    db = request.app.state.db
    embedder = request.app.state.embedder
    ctx = auth_context(request)

    if not ctx.has_role("editor"):
        return JSONResponse(status_code=403, content={"error": "Write access requires editor role"})

    workspace, project = ctx.clamp_scope(body.workspace, body.project)

    entry_scan = parse_entry_items([(f.path, f.text) for f in body.entries])
    col_scan = parse_collection_items([(f.slug, f.text) for f in body.collections])
    file_errors = [
        {"path": e.path, "message": e.message} for e in entry_scan.errors + col_scan.errors
    ]
    if file_errors:
        return JSONResponse(
            status_code=422, content={"error": "off-spec files", "files": file_errors}
        )

    drift = check_drift(col_scan.collections, body.manifest)
    if not drift.ok:
        return JSONResponse(
            status_code=422, content={"error": "drift", "issues": drift.errors}
        )

    outcome = await apply_push(
        db, embedder, entry_scan.entries, col_scan.collections,
        org_id=ctx.org_id, workspace=workspace, project=project,
    )
    if not outcome.ok:
        return JSONResponse(
            status_code=409,
            content={
                "error": "server-canonical collection conflict",
                "conflicts": outcome.conflicts,
            },
        )

    return {
        "created": outcome.created,
        "updated": outcome.updated,
        "collections": outcome.collections,
        "documents": outcome.documents,
        "warnings": drift.warnings,
    }


@router.get("/export")
async def export_bundle(
    request: Request,
    workspace: str | None = None,
    project: str | None = None,
):
    """Return a rendered bundle as ``{files: [{path, content}]}``.

    The server renders entries, repo collections, manifest, and viewer; the
    client just writes the files. Live (server-canonical) stores are excluded.
    """
    db = request.app.state.db
    ctx = auth_context(request)
    workspace, project = ctx.clamp_scope(workspace, project)

    entries, collections = await gather_export(
        db, org_id=ctx.org_id, workspace=workspace, project=project
    )
    files = render_bundle(entries, collections)
    return {
        "files": [{"path": path, "content": content} for path, content in files.items()],
        "entries": len(entries),
        "collections": len(collections),
    }
