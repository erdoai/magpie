"""Activity feed — a chronological view of recent changes across the store.

Merges recent entry writes and KV writes into one time-ordered timeline so you
can see what's been happening. Derived from existing rows (no audit table):
created vs. updated is inferred from created_at == updated_at.
"""

from fastapi import APIRouter, Request

from magpie.server.context import auth_context

router = APIRouter(prefix="/api")


def _action(created_at, updated_at, *, archived: bool = False) -> str:
    if archived:
        return "archived"
    return "created" if created_at == updated_at else "updated"


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


@router.get("/updates")
async def list_updates(
    request: Request,
    workspace: str | None = None,
    project: str | None = None,
    limit: int = 50,
):
    """Recent activity across entries and KV stores, newest first.

    Org-scoped via the caller's context; optional workspace/project narrow it.
    """
    db = request.app.state.db
    ctx = auth_context(request)
    workspace, project = ctx.clamp_scope(workspace, project)
    limit = max(1, min(limit, 100))

    entries = await db.list_entries(
        user_id=ctx.user_id,
        org_id=ctx.org_id,
        workspace=workspace,
        project=project,
        limit=limit,
    )
    pairs = await db.list_recent_kv_pairs(
        org_id=ctx.org_id, workspace=workspace, project=project, limit=limit
    )

    items: list[dict] = []
    for e in entries:
        items.append({
            "kind": "entry",
            "action": _action(
                e["created_at"], e["updated_at"], archived=e.get("category") == "archive"
            ),
            "title": e["title"],
            "entry_id": e["id"],
            "store": None,
            "key": None,
            "value_type": None,
            "workspace": e.get("workspace"),
            "project": e.get("project"),
            "at": _iso(e["updated_at"]),
        })
    for p in pairs:
        items.append({
            "kind": "kv",
            "action": _action(p["created_at"], p["updated_at"]),
            "title": f"{p['store_slug']}/{p['key']}",
            "entry_id": None,
            "store": p["store_slug"],
            "key": p["key"],
            "value_type": p["value_type"],
            "workspace": p.get("workspace"),
            "project": p.get("project"),
            "at": _iso(p["updated_at"]),
        })

    items.sort(key=lambda i: i["at"] or "", reverse=True)
    return items[:limit]
