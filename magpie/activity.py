"""Activity-log emission — one place every write surface calls to append an
event, so they can never drift on action names or event shape.

Why this module exists: the REST routes and the hosted MCP server both write to
the DB *directly* (the MCP server isn't a REST client), so emission can't live
in the routes alone or MCP-driven writes would vanish from the feed. The stdio
CLI MCP and the TypeScript CLI proxy REST, so they inherit emission for free;
this covers the two direct-DB surfaces.

Action names are namespaced (``entry.created``, not bare ``created``) so the
feed is scannable and the set is safe to extend. Emission is best-effort:
``Database.record_activity`` swallows and logs its own errors, so a logging
failure never fails a write that already committed.
"""

from magpie.server.context import AuthContext

# -- Action constants (the canonical, namespaced set) --

ENTRY_CREATED = "entry.created"
ENTRY_UPDATED = "entry.updated"
ENTRY_ARCHIVED = "entry.archived"
ENTRY_UNARCHIVED = "entry.unarchived"
ENTRY_DELETED = "entry.deleted"
ENTRY_MERGED = "entry.merged"
ENTRY_BULK_UPDATED = "entry.bulk_updated"
KV_STORE_CREATED = "kv_store.created"
KV_STORE_DELETED = "kv_store.deleted"
KV_PAIR_SET = "kv_pair.set"
KV_PAIR_DELETED = "kv_pair.deleted"
ATTACHMENT_ADDED = "attachment.added"
ATTACHMENT_DELETED = "attachment.deleted"
BUNDLE_PUSHED = "bundle.pushed"


async def _emit(
    db,
    ctx: AuthContext,
    *,
    action: str,
    subject_type: str,
    subject_id: str | None = None,
    subject_title: str | None = None,
    org_id: str | None = None,
    workspace: str | None = None,
    project: str | None = None,
    metadata: dict | None = None,
) -> None:
    await db.record_activity(
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        subject_title=subject_title,
        org_id=org_id,
        workspace=workspace,
        project=project,
        metadata=metadata,
        **ctx.actor,
    )


# -- Entries (``entry`` is a full row dict: id/title/org_id/workspace/project) --


async def entry_created(db, ctx: AuthContext, entry: dict) -> None:
    await _emit(
        db, ctx, action=ENTRY_CREATED, subject_type="entry",
        subject_id=entry["id"], subject_title=entry.get("title"),
        org_id=entry.get("org_id"), workspace=entry.get("workspace"),
        project=entry.get("project"),
    )


async def entry_updated(db, ctx: AuthContext, entry: dict, changed: list[str]) -> None:
    await _emit(
        db, ctx, action=ENTRY_UPDATED, subject_type="entry",
        subject_id=entry["id"], subject_title=entry.get("title"),
        org_id=entry.get("org_id"), workspace=entry.get("workspace"),
        project=entry.get("project"), metadata={"changed": changed},
    )


async def entry_archived(db, ctx: AuthContext, entry: dict, *, archived: bool) -> None:
    await _emit(
        db, ctx, action=ENTRY_ARCHIVED if archived else ENTRY_UNARCHIVED,
        subject_type="entry", subject_id=entry["id"],
        subject_title=entry.get("title"), org_id=entry.get("org_id"),
        workspace=entry.get("workspace"), project=entry.get("project"),
    )


async def entry_deleted(db, ctx: AuthContext, entry: dict) -> None:
    await _emit(
        db, ctx, action=ENTRY_DELETED, subject_type="entry",
        subject_id=entry["id"], subject_title=entry.get("title"),
        org_id=entry.get("org_id"), workspace=entry.get("workspace"),
        project=entry.get("project"),
    )


async def entry_merged(db, ctx: AuthContext, entry: dict, source_ids: list[str]) -> None:
    await _emit(
        db, ctx, action=ENTRY_MERGED, subject_type="entry",
        subject_id=entry["id"], subject_title=entry.get("title"),
        org_id=entry.get("org_id"), workspace=entry.get("workspace"),
        project=entry.get("project"),
        metadata={"source_ids": source_ids, "new_entry_id": entry["id"]},
    )


async def entry_bulk_updated(
    db,
    ctx: AuthContext,
    *,
    match: dict,
    changes: dict,
    matched: int,
    updated: int,
    org_id: str | None,
    workspace: str | None,
    project: str | None,
) -> None:
    await _emit(
        db, ctx, action=ENTRY_BULK_UPDATED, subject_type="entry",
        org_id=org_id, workspace=workspace, project=project,
        metadata={
            "match": match, "changes": changes,
            "matched": matched, "updated": updated,
        },
    )


# -- KV (``store`` is a full kv_stores row dict) --


async def kv_store_created(db, ctx: AuthContext, store: dict) -> None:
    await _emit(
        db, ctx, action=KV_STORE_CREATED, subject_type="kv_store",
        subject_id=store["id"], subject_title=store.get("slug"),
        org_id=store.get("org_id"), workspace=store.get("workspace"),
        project=store.get("project"),
    )


async def kv_store_deleted(db, ctx: AuthContext, store: dict) -> None:
    await _emit(
        db, ctx, action=KV_STORE_DELETED, subject_type="kv_store",
        subject_id=store["id"], subject_title=store.get("slug"),
        org_id=store.get("org_id"), workspace=store.get("workspace"),
        project=store.get("project"),
    )


async def kv_pair_set(
    db, ctx: AuthContext, store: dict, key: str, value_type: str, *, created: bool
) -> None:
    await _emit(
        db, ctx, action=KV_PAIR_SET, subject_type="kv_pair",
        subject_id=store["id"], subject_title=f"{store.get('slug')}/{key}",
        org_id=store.get("org_id"), workspace=store.get("workspace"),
        project=store.get("project"),
        metadata={
            "store": store.get("slug"), "key": key,
            "value_type": value_type, "created": created,
        },
    )


async def kv_pair_deleted(db, ctx: AuthContext, store: dict, key: str) -> None:
    await _emit(
        db, ctx, action=KV_PAIR_DELETED, subject_type="kv_pair",
        subject_id=store["id"], subject_title=f"{store.get('slug')}/{key}",
        org_id=store.get("org_id"), workspace=store.get("workspace"),
        project=store.get("project"),
        metadata={"store": store.get("slug"), "key": key},
    )


# -- Attachments (scope inherited from the owning ``entry``) --


async def attachment_added(db, ctx: AuthContext, att: dict, entry: dict) -> None:
    await _emit(
        db, ctx, action=ATTACHMENT_ADDED, subject_type="attachment",
        subject_id=att["id"], subject_title=att.get("filename"),
        org_id=entry.get("org_id"), workspace=entry.get("workspace"),
        project=entry.get("project"),
        metadata={
            "filename": att.get("filename"), "role": att.get("role"),
            "media_type": att.get("media_type"), "byte_size": att.get("byte_size"),
            "entry_id": entry.get("id"),
        },
    )


async def attachment_deleted(db, ctx: AuthContext, att: dict, entry: dict) -> None:
    await _emit(
        db, ctx, action=ATTACHMENT_DELETED, subject_type="attachment",
        subject_id=att["id"], subject_title=att.get("filename"),
        org_id=entry.get("org_id"), workspace=entry.get("workspace"),
        project=entry.get("project"),
        metadata={"filename": att.get("filename"), "entry_id": entry.get("id")},
    )


# -- Bundle push --


async def bundle_pushed(
    db,
    ctx: AuthContext,
    *,
    org_id: str | None,
    workspace: str | None,
    project: str | None,
    entries: int,
    stores: int,
    pairs: int,
) -> None:
    scope = workspace or "all"
    if project:
        scope = f"{workspace}/{project}"
    await _emit(
        db, ctx, action=BUNDLE_PUSHED, subject_type="bundle",
        subject_title=scope, org_id=org_id, workspace=workspace, project=project,
        metadata={"entries": entries, "stores": stores, "pairs": pairs},
    )
