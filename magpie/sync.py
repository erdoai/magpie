"""Shared push/export logic, used by both the Python CLI and the REST API.

Keeping this in one place is the point: ``magpie push`` (Python CLI, direct DB)
and ``POST /api/bundle/push`` (REST, for the TS CLI) run the *same* upsert,
server-conflict, and collection-sync code, so the two surfaces can never drift
apart. Validation and anti-drift parsing live in :mod:`magpie.bundle` and
:mod:`magpie.manifest`; this module applies the parsed result to the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from magpie.bundle import BundleCollection, BundleEntry
from magpie.links import sync_entry_links


@dataclass
class PushOutcome:
    created: int = 0
    updated: int = 0
    collections: int = 0
    documents: int = 0
    # Slugs that already exist as live (server-canonical) stores — a refusal,
    # set when the push was rejected before any writes.
    conflicts: list[str] = field(default_factory=list)
    # (verb, path) per entry, for callers that want to log progress.
    entry_log: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts


async def _collection_conflicts(
    db, collections: list[BundleCollection], *, org_id, workspace, project
) -> tuple[list[str], dict[str, dict]]:
    """Find repo collections that collide with a live server-canonical store."""
    conflicts: list[str] = []
    existing: dict[str, dict] = {}
    for col in collections:
        found = await db.find_collection(
            col.slug, org_id=org_id, workspace=workspace, project=project
        )
        if found and found.get("org_id") == org_id:
            if found.get("source") != "repo":
                conflicts.append(col.slug)
            existing[col.slug] = found
    return conflicts, existing


async def apply_push(
    db,
    embedder,
    entries: list[BundleEntry],
    collections: list[BundleCollection],
    *,
    org_id: str | None = None,
    workspace: str | None = None,
    project: str | None = None,
) -> PushOutcome:
    """Apply a parsed, drift-checked bundle to the database.

    Caller is responsible for parsing (``magpie.bundle``) and anti-drift checks
    (``magpie.manifest.check_drift``) first. This does the server-side
    server-conflict pre-check, then upserts entries and repo collections.
    """
    outcome = PushOutcome()

    conflicts, existing = await _collection_conflicts(
        db, collections, org_id=org_id, workspace=workspace, project=project
    )
    if conflicts:
        outcome.conflicts = conflicts
        return outcome  # refuse before writing anything

    for entry in entries:
        fm = entry.frontmatter
        embedding = None
        if embedder:
            try:
                embedding = await embedder.embed(f"{entry.title}\n{entry.body}")
            except Exception:
                pass
        entry_id, was_updated = await db.upsert_entry_by_path(
            source_path=entry.path,
            title=entry.title,
            content=entry.body,
            category=fm.category,
            tags=fm.tags,
            source=fm.source or "bundle",
            embedding=embedding,
            org_id=org_id,
            workspace=workspace,
            project=project,
        )
        await sync_entry_links(db, entry_id)
        outcome.updated += was_updated
        outcome.created += not was_updated
        outcome.entry_log.append(("updated" if was_updated else "created", entry.path))

    for col in collections:
        found = existing.get(col.slug)
        if found:
            col_id = found["id"]
        else:
            col_id = await db.create_collection(
                slug=col.slug,
                title=col.slug,
                org_id=org_id,
                workspace=workspace,
                project=project,
                source="repo",
            )
        for doc in col.documents:
            await db.set_document(
                collection_id=col_id,
                key=doc.key,
                value=doc.value,
                value_type=doc.value_type,
                org_id=org_id,
            )
            outcome.documents += 1
        outcome.collections += 1

    return outcome


async def gather_export(
    db, *, org_id: str | None = None, workspace: str | None = None, project: str | None = None
) -> tuple[list[dict], list[dict]]:
    """Collect entries and repo-canonical collections for export.

    Returns ``(entries, collections)`` where collections are
    ``{"slug", "title", "documents"}`` dicts. Live (server-canonical) stores are
    excluded so an export never drags runtime data into a bundle.
    """
    entries: list[dict] = []
    offset = 0
    while True:
        batch = await db.list_entries(
            org_id=org_id, workspace=workspace, project=project, offset=offset, limit=200
        )
        if not batch:
            break
        entries.extend(batch)
        offset += len(batch)

    collections: list[dict] = []
    for col in await db.list_collections(org_id=org_id, workspace=workspace, project=project):
        if col.get("source") != "repo":
            continue
        documents = await db.list_documents(col["id"])
        collections.append(
            {"slug": col["slug"], "title": col.get("title"), "documents": documents}
        )

    return entries, collections
