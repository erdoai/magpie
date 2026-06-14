"""Shared logic for bulk entry operations (rescope / retag).

Both the REST route and the remote MCP tool funnel through here so the role
gate, key-scope clamp, and validation live once. Each surface only builds the
raw ``match``/``changes`` dicts from its own input shape, then calls
:func:`run_bulk`; the dangerous decisions (who may apply, what may be cleared,
refusing an empty match) are made here.
"""

from dataclasses import dataclass

from magpie import activity
from magpie.server.context import AuthContext

# Only these fields may be nulled via ``clear`` — scope tags, never content.
CLEARABLE = ("workspace", "project")


@dataclass
class BulkError:
    """A validation/authorization failure. Surfaces map it to HTTP or text."""

    status: int
    message: str


def build_match(
    *,
    workspace: str | None = None,
    project: str | None = None,
    tags: list[str] | None = None,
    source: str | None = None,
) -> dict:
    """Assemble the entry-selection filter, dropping unset keys."""
    match: dict = {}
    if workspace is not None:
        match["workspace"] = workspace
    if project is not None:
        match["project"] = project
    if tags:
        match["tags"] = tags
    if source is not None:
        match["source"] = source
    return match


def build_changes(
    *,
    workspace: str | None = None,
    project: str | None = None,
    add_tags: list[str] | None = None,
    remove_tags: list[str] | None = None,
    rename_from: str | None = None,
    rename_to: str | None = None,
    clear: list[str] | None = None,
) -> dict:
    """Assemble the mutation spec. Only meaningful, well-formed ops survive."""
    changes: dict = {}
    if workspace is not None:
        changes["workspace"] = workspace
    if project is not None:
        changes["project"] = project
    if add_tags:
        changes["add_tags"] = add_tags
    if remove_tags:
        changes["remove_tags"] = remove_tags
    if rename_from and rename_to:
        changes["rename_from"] = rename_from
        changes["rename_to"] = rename_to
    if clear:
        allowed = [f for f in clear if f in CLEARABLE]
        if allowed:
            changes["clear"] = allowed
    return changes


async def run_bulk(
    db,
    ctx: AuthContext,
    *,
    match: dict,
    changes: dict,
    dry_run: bool,
) -> dict | BulkError:
    """Validate, authorize, and dispatch a bulk update.

    Previewing (dry-run) needs editor; applying needs admin — a mass mutation
    is higher blast radius than a single write. Returns the DB result dict, or
    a :class:`BulkError` the caller renders for its surface.
    """
    if not ctx.has_role("editor"):
        return BulkError(403, "Bulk operations require editor role")
    if not dry_run and not ctx.has_role("admin"):
        return BulkError(403, "Applying a bulk change requires admin role")

    # A workspace/project-pinned key clamps which entries are even selectable.
    ws, proj = ctx.clamp_scope(match.get("workspace"), match.get("project"))
    if ws is not None:
        match["workspace"] = ws
    if proj is not None:
        match["project"] = proj
    match = {k: v for k, v in match.items() if v is not None}

    if not match:
        return BulkError(
            400, "match requires at least one filter (workspace, project, tags, or source)"
        )
    if not changes:
        return BulkError(400, "changes must specify at least one mutation")

    result = await db.bulk_update_entries(
        match=match,
        changes=changes,
        user_id=ctx.user_id,
        org_id=ctx.org_id,
        trusted=ctx.is_unrestricted,
        dry_run=dry_run,
    )

    # One event per applied bulk op (never for a dry-run preview). Emitted here,
    # the shared chokepoint, so REST and the MCP bulk_edit tool stay in lockstep.
    if result.get("applied"):
        await activity.entry_bulk_updated(
            db, ctx,
            match=match, changes=changes,
            matched=result["matched"], updated=result["updated"],
            org_id=ctx.org_id,
            workspace=match.get("workspace"),
            project=match.get("project"),
        )

    return result
