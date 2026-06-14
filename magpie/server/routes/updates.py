"""Activity feed — a chronological view of recent changes across the store.

Reads the append-only ``activity_events`` log (see ``magpie/activity.py``), so
the feed is durable: it survives overwrites and deletes, records who acted, and
covers entries, KV, attachments, merges, bulk edits, and bundle pushes — not
just current row state. Each event is returned in two shapes at once: a small
back-compatible projection (``kind``/``action``/``title``/…) the existing UI
already renders, plus the richer event fields (actor, subject, metadata).
"""

from fastapi import APIRouter, Request

from magpie.server.context import auth_context

router = APIRouter(prefix="/api")

# Map an event's subject_type to the coarse `kind` the feed UI groups by.
_KIND = {
    "entry": "entry",
    "kv_store": "kv",
    "kv_pair": "kv",
    "attachment": "attachment",
    "bundle": "bundle",
}


def _project(event: dict) -> dict:
    """Render one activity event as a feed item: back-compat fields plus the
    full event shape. ``action`` is the verb (the part after the dot)."""
    action = event["action"]
    _, _, verb = action.partition(".")
    subject_type = event["subject_type"]
    metadata = event.get("metadata_json") or {}
    created_at = event.get("created_at")
    return {
        # -- back-compatible projection (the original /api/updates shape) --
        "kind": _KIND.get(subject_type, subject_type),
        "action": verb or action,
        "title": event.get("subject_title"),
        "entry_id": event.get("subject_id") if subject_type == "entry" else None,
        "store": metadata.get("store"),
        "key": metadata.get("key"),
        "value_type": metadata.get("value_type"),
        "workspace": event.get("workspace"),
        "project": event.get("project"),
        "at": created_at.isoformat() if created_at else None,
        # -- richer event shape --
        "id": event["id"],
        "subject_type": subject_type,
        "subject_id": event.get("subject_id"),
        "subject_title": event.get("subject_title"),
        "actor_user_id": event.get("actor_user_id"),
        "actor_type": event.get("actor_type"),
        "metadata": metadata,
    }


@router.get("/updates")
async def list_updates(
    request: Request,
    workspace: str | None = None,
    project: str | None = None,
    limit: int = 50,
):
    """Recent activity across the store, newest first.

    Org-scoped via the caller's context; optional workspace/project narrow it.
    """
    db = request.app.state.db
    ctx = auth_context(request)
    workspace, project = ctx.clamp_scope(workspace, project)
    limit = max(1, min(limit, 100))

    events = await db.list_activity(
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        workspace=workspace,
        project=project,
        limit=limit,
        trusted=ctx.is_unrestricted,
    )
    return [_project(e) for e in events]
