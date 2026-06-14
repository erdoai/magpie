"""Shared push/export logic, used by both the Python CLI and the REST API.

Keeping this in one place is the point: ``magpie push`` (Python CLI, direct DB)
and ``POST /api/bundle/push`` (REST, for the TS CLI) run the *same* upsert,
server-conflict, and kv-sync code, so the two surfaces can never drift
apart. Validation and anti-drift parsing live in :mod:`magpie.bundle` and
:mod:`magpie.manifest`; this module applies the parsed result to the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from magpie.bundle import BundleEntry, BundleKvStore
from magpie.links import sync_entry_links


@dataclass
class PushOutcome:
    created: int = 0
    updated: int = 0
    stores: int = 0
    pairs: int = 0
    # Slugs that already exist as live (server-canonical) stores — a refusal,
    # set when the push was rejected before any writes.
    conflicts: list[str] = field(default_factory=list)
    # (verb, path) per entry, for callers that want to log progress.
    entry_log: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts


async def _store_conflicts(
    db, stores: list[BundleKvStore], *, org_id, workspace, project
) -> tuple[list[str], dict[str, dict]]:
    """Find repo kv stores that collide with a live server-canonical store."""
    conflicts: list[str] = []
    existing: dict[str, dict] = {}
    for store in stores:
        found = await db.find_kv_store(
            store.slug, org_id=org_id, workspace=workspace, project=project
        )
        if found and found.get("org_id") == org_id:
            if found.get("source") != "repo":
                conflicts.append(store.slug)
            existing[store.slug] = found
    return conflicts, existing


async def apply_push(
    db,
    embedder,
    entries: list[BundleEntry],
    stores: list[BundleKvStore],
    *,
    org_id: str | None = None,
    workspace: str | None = None,
    project: str | None = None,
) -> PushOutcome:
    """Apply a parsed, drift-checked bundle to the database.

    Caller is responsible for parsing (``magpie.bundle``) and anti-drift checks
    (``magpie.manifest.check_drift``) first. This does the server-side
    server-conflict pre-check, then upserts entries and repo kv stores.
    """
    outcome = PushOutcome()

    conflicts, existing = await _store_conflicts(
        db, stores, org_id=org_id, workspace=workspace, project=project
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
            tags=fm.tags,
            source=fm.source or "bundle",
            embedding=embedding,
            org_id=org_id,
            workspace=workspace,
            project=project,
            archived=fm.archived,
        )
        await sync_entry_links(db, entry_id)
        outcome.updated += was_updated
        outcome.created += not was_updated
        outcome.entry_log.append(("updated" if was_updated else "created", entry.path))

    for store in stores:
        found = existing.get(store.slug)
        if found:
            store_id = found["id"]
        else:
            store_id = await db.create_kv_store(
                slug=store.slug,
                title=store.slug,
                org_id=org_id,
                workspace=workspace,
                project=project,
                source="repo",
            )
        for pair in store.pairs:
            await db.set_kv_pair(
                store_id=store_id,
                key=pair.key,
                value=pair.value,
                value_type=pair.value_type,
                org_id=org_id,
            )
            outcome.pairs += 1
        outcome.stores += 1

    return outcome


async def gather_export(
    db, *, org_id: str | None = None, workspace: str | None = None, project: str | None = None
) -> tuple[list[dict], list[dict]]:
    """Collect entries and repo-canonical kv stores for export.

    Returns ``(entries, stores)`` where stores are
    ``{"slug", "title", "pairs"}`` dicts. Live (server-canonical) stores are
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

    stores: list[dict] = []
    for store in await db.list_kv_stores(org_id=org_id, workspace=workspace, project=project):
        if store.get("source") != "repo":
            continue
        pairs = await db.list_kv_pairs(store["id"])
        stores.append(
            {"slug": store["slug"], "title": store.get("title"), "pairs": pairs}
        )

    return entries, stores
