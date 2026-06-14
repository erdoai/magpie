"""Magpie CLI — knowledge store with dual search."""

import asyncio
import logging
import mimetypes
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import typer
import uvicorn
from rich.console import Console

from magpie import activity
from magpie.__version__ import __version__
from magpie.attachments import handle_for, infer_kind, storage_key_for
from magpie.bulk import build_changes, build_match
from magpie.bundle import load_manifest, scan_entries, scan_kv_stores
from magpie.config.settings import Settings
from magpie.db.database import Database
from magpie.db.migrate import run_migrations
from magpie.embeddings.openai import OpenAIEmbeddings
from magpie.export import write_bundle
from magpie.links import sync_entry_links
from magpie.manifest import check_drift
from magpie.server.context import AuthContext
from magpie.storage import create_storage
from magpie.sync import apply_push, gather_export

app = typer.Typer(help="magpie — knowledge store with semantic + keyword search")
attachments_app = typer.Typer(help="Manage entry attachments")
app.add_typer(attachments_app, name="attachments")
console = Console()


@app.command()
def serve(
    host: str = typer.Option(None, help="Override MAGPIE_HOST"),
    port: int = typer.Option(None, help="Override MAGPIE_PORT"),
):
    """Start the magpie server (REST + MCP)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")

    settings = Settings()
    # Railway injects PORT env var
    resolved_port = port or int(os.environ.get("PORT", 0)) or settings.port
    uvicorn.run(
        "magpie.server.app:create_app",
        factory=True,
        host=host or settings.host,
        port=resolved_port,
        log_level="info",
    )


@app.command()
def migrate():
    """Run database migrations only (no server)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")

    settings = Settings()
    if not settings.database_url:
        console.print("[red]DATABASE_URL is not set[/red]")
        raise typer.Exit(1)

    async def _run():
        pool = await asyncpg.create_pool(settings.database_url)
        await run_migrations(pool)
        await pool.close()
        console.print("[green]Migrations applied successfully[/green]")

    asyncio.run(_run())


@app.command(name="import")
def import_cmd(
    source: str = typer.Argument(help="Import source: 'claude' or 'markdown'"),
    path: str = typer.Argument(
        None, help="Path to import from (default: ~/.claude for claude, current dir for markdown)"
    ),
    workspace: str = typer.Option("general", help="Workspace to import into"),
    project: str = typer.Option(None, help="Project within the workspace"),
):
    """Import knowledge from external sources."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")

    settings = Settings()
    if not settings.database_url:
        console.print("[red]DATABASE_URL is not set[/red]")
        raise typer.Exit(1)

    async def _run():
        db = await Database.connect(settings.database_url)

        embedder = None
        if settings.openai_api_key:
            embedder = OpenAIEmbeddings(
                api_key=settings.openai_api_key,
                model=settings.embedding_model,
                dims=settings.embedding_dimensions,
            )

        count = 0

        if source == "claude":
            # Import from .claude/projects/*/memory/ directories
            base = Path(path) if path else Path.home() / ".claude"
            for memory_dir in base.rglob("memory"):
                if not memory_dir.is_dir():
                    continue
                for md_file in sorted(memory_dir.glob("*.md")):
                    if md_file.name == "MEMORY.md":
                        continue
                    count += await _import_markdown_file(
                        db, embedder, md_file, workspace, project, source="claude-code"
                    )

        elif source == "markdown":
            # Import markdown files from a directory
            base = Path(path) if path else Path(".")
            for md_file in sorted(base.rglob("*.md")):
                count += await _import_markdown_file(
                    db, embedder, md_file, workspace, project, source="markdown"
                )

        else:
            console.print(f"[red]Unknown source: {source}. Use 'claude' or 'markdown'.[/red]")
            raise typer.Exit(1)

        if embedder:
            await embedder.close()
        await db.close()
        console.print(f"[green]Imported {count} entries into workspace '{workspace}'[/green]")

    asyncio.run(_run())


async def _import_markdown_file(db, embedder, file_path, workspace, project, source):
    """Import a single markdown file as an entry. Returns 1 if imported, 0 if skipped."""
    text = file_path.read_text().strip()
    if not text:
        return 0

    # Parse YAML frontmatter if present
    title = file_path.stem.replace("_", " ").replace("-", " ").title()
    tags = []

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            text = parts[2].strip()

            for line in frontmatter.strip().split("\n"):
                if line.startswith("name:"):
                    title = line.split(":", 1)[1].strip().strip('"')
                elif line.startswith("description:"):
                    pass  # use content instead

    if not text:
        return 0

    embedding = None
    if embedder:
        try:
            embedding = await embedder.embed(f"{title}\n{text}")
        except Exception:
            pass

    entry_id = await db.create_entry(
        title=title,
        content=text,
        tags=tags,
        source=source,
        embedding=embedding,
        workspace=workspace,
        project=project,
    )
    await sync_entry_links(db, entry_id)

    console.print(f"  Imported: {title}")
    return 1


@app.command()
def push(
    directory: str = typer.Argument(".", help="Bundle directory to push"),
    workspace: str = typer.Option("general", help="Workspace to sync into"),
    project: str = typer.Option(None, help="Project within the workspace"),
    org_id: str = typer.Option(None, help="Org to own the entries (NULL = global)"),
):
    """Sync a knowledge bundle to the server (repo = source of truth).

    Entries are matched by their relative path within the bundle, so re-running
    updates in place instead of creating duplicates. Every Markdown file must
    carry valid Magpie frontmatter; if any file is off-spec the push aborts and
    reports every problem, leaving the server untouched.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")

    settings = Settings()
    if not settings.database_url:
        console.print("[red]DATABASE_URL is not set[/red]")
        raise typer.Exit(1)

    result = scan_entries(directory)
    kv_result = scan_kv_stores(directory)
    manifest, manifest_err = load_manifest(directory)
    file_errors = list(result.errors) + list(kv_result.errors)
    if manifest_err:
        file_errors.append(manifest_err)
    if file_errors:
        console.print(f"[red]Refusing to push — {len(file_errors)} file(s) off-spec:[/red]")
        for err in file_errors:
            console.print(f"  [red]{err.path}[/red]: {err.message}")
        raise typer.Exit(1)

    # Anti-drift: reject undeclared/near-duplicate kv stores before any writes.
    drift = check_drift(kv_result.stores, manifest)
    for warning in drift.warnings:
        console.print(f"  [yellow]warning[/yellow]: {warning}")
    if not drift.ok:
        console.print(f"[red]Refusing to push — {len(drift.errors)} drift issue(s):[/red]")
        for err in drift.errors:
            console.print(f"  [red]{err}[/red]")
        raise typer.Exit(1)

    if not result.entries and not kv_result.stores:
        console.print("[yellow]No entries or kv stores found in bundle.[/yellow]")
        return

    async def _run():
        db = await Database.connect(settings.database_url)

        embedder = None
        if settings.openai_api_key:
            embedder = OpenAIEmbeddings(
                api_key=settings.openai_api_key,
                model=settings.embedding_model,
                dims=settings.embedding_dimensions,
            )

        outcome = await apply_push(
            db, embedder, result.entries, kv_result.stores,
            org_id=org_id, workspace=workspace, project=project,
        )

        # Operator push from the repo — recorded as a system actor.
        if outcome.ok:
            await activity.bundle_pushed(
                db, AuthContext(actor_type="system"),
                org_id=org_id, workspace=workspace, project=project,
                entries=outcome.created + outcome.updated,
                stores=outcome.stores, pairs=outcome.pairs,
            )

        if embedder:
            await embedder.close()
        await db.close()

        if not outcome.ok:
            console.print(
                "[red]Refusing to push — these kv stores already exist as "
                "server-canonical (live) stores:[/red]"
            )
            for slug in outcome.conflicts:
                console.print(f"  [red]{slug}[/red]: edit it via the API/agent, not the repo")
            raise typer.Exit(1)

        for verb, path in outcome.entry_log:
            console.print(f"  {verb}: {path}")
        console.print(
            f"[green]Pushed {len(result.entries)} entries "
            f"({outcome.created} created, {outcome.updated} updated) and "
            f"{outcome.stores} repo kv stores ({outcome.pairs} keys) "
            f"into '{workspace}'[/green]"
        )

    asyncio.run(_run())


@app.command()
def export(
    directory: str = typer.Argument(help="Directory to write the bundle into"),
    workspace: str = typer.Option(None, help="Limit to a workspace"),
    project: str = typer.Option(None, help="Limit to a project"),
    org_id: str = typer.Option(None, help="Limit to an org (NULL = global)"),
):
    """Export entries and repo-canonical kv stores as a bundle on disk.

    The inverse of `push`: writes Markdown entries (re-using their original
    paths) and `kv/<slug>.json` for repo-canonical stores, plus a
    generated `_manifest.json`. Live (server-canonical) kv stores are not
    exported — runtime data stays out of the bundle.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")

    settings = Settings()
    if not settings.database_url:
        console.print("[red]DATABASE_URL is not set[/red]")
        raise typer.Exit(1)

    async def _run():
        db = await Database.connect(settings.database_url)
        entries, stores = await gather_export(
            db, org_id=org_id, workspace=workspace, project=project
        )
        await db.close()
        summary = write_bundle(directory, entries, stores)
        console.print(
            f"[green]Exported {summary['entries']} entries and "
            f"{summary['stores']} repo kv stores to {directory}[/green]"
        )

    asyncio.run(_run())


@attachments_app.command("add")
def attachments_add(
    entry_id: str = typer.Argument(help="Entry to attach to"),
    file: str = typer.Argument(help="Path to the file"),
    role: str = typer.Option(None, help="Role tag (e.g. logo-primary, query-revenue)"),
    description: str = typer.Option(None, help="What this is and when to use it"),
    public: bool = typer.Option(False, help="Serve via /public/assets (images only)"),
):
    """Attach a file to a knowledge entry."""
    settings = Settings()
    if not settings.database_url:
        console.print("[red]DATABASE_URL is not set[/red]")
        raise typer.Exit(1)

    path = Path(file)
    if not path.is_file():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    async def _run():
        db = await Database.connect(settings.database_url)
        storage = create_storage(settings)
        if not storage:
            console.print("[red]Attachment storage not configured[/red]")
            await db.close()
            raise typer.Exit(1)

        # Server-side CLI op against the DB — full access by design.
        entry = await db.get_entry(entry_id, trusted=True)
        if not entry:
            console.print(f"[red]Entry {entry_id} not found[/red]")
            await db.close()
            raise typer.Exit(1)

        data = path.read_bytes()
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        kind = infer_kind(path.name, media_type)

        att_id = uuid4().hex
        storage_key = storage_key_for(entry.get("org_id"), entry_id, att_id, path.name)
        await storage.put(storage_key, data, media_type)
        await db.create_attachment(
            att_id=att_id,
            entry_id=entry_id,
            kind=kind,
            filename=path.name,
            media_type=media_type,
            storage_key=storage_key,
            byte_size=len(data),
            org_id=entry.get("org_id"),
            description=description,
            role=role,
            public=public,
        )
        await storage.close()
        await db.close()
        console.print(
            f"[green]Attached {path.name} ({kind}, {len(data)} bytes)[/green]\n"
            f"Handle: {handle_for(att_id)}"
        )

    asyncio.run(_run())


@attachments_app.command("list")
def attachments_list(entry_id: str = typer.Argument(help="Entry ID")):
    """List attachments on a knowledge entry."""
    settings = Settings()
    if not settings.database_url:
        console.print("[red]DATABASE_URL is not set[/red]")
        raise typer.Exit(1)

    async def _run():
        db = await Database.connect(settings.database_url)
        attachments = await db.list_attachments(entry_id)
        await db.close()
        if not attachments:
            console.print("No attachments.")
            return
        for att in attachments:
            role = f" [cyan]{att['role']}[/cyan]" if att.get("role") else ""
            console.print(
                f"- {att['filename']} [{att['kind']}]{role}"
                f" ({att['byte_size']} bytes) {handle_for(att['id'])}"
            )

    asyncio.run(_run())


def _print_bulk(result: dict, apply: bool) -> None:
    for s in result["sample"]:
        before, after = s["before"], s["after"]
        bs = f"{before['workspace'] or '—'}/{before['project'] or '—'} {before['tags']}"
        as_ = f"{after['workspace'] or '—'}/{after['project'] or '—'} {after['tags']}"
        console.print(f"  - {s['title']}: {bs} → {as_}")
    if result["applied"]:
        n = result["updated"]
        console.print(f"[green]Applied to {n} entr{'y' if n == 1 else 'ies'}.[/green]")
    else:
        n = result["matched"]
        console.print(
            f"[yellow]Dry run: {n} entr{'y' if n == 1 else 'ies'} would change. "
            f"Re-run with --apply to commit.[/yellow]"
        )


async def _run_bulk(match: dict, changes: dict, apply: bool) -> None:
    settings = Settings()
    if not settings.database_url:
        console.print("[red]DATABASE_URL is not set[/red]")
        raise typer.Exit(1)
    if not match:
        console.print("[red]Refusing to run — provide at least one match filter[/red]")
        raise typer.Exit(1)
    if not changes:
        console.print("[red]Refusing to run — provide at least one change[/red]")
        raise typer.Exit(1)

    db = await Database.connect(settings.database_url)
    # Server-side op against the DB: trusted, no tenant boundary (operator tool).
    result = await db.bulk_update_entries(
        match=match, changes=changes, trusted=True, dry_run=not apply
    )
    await db.close()
    _print_bulk(result, apply)


@app.command()
def rescope(
    workspace: str = typer.Option(None, help="Match: only entries in this workspace"),
    project: str = typer.Option(None, help="Match: only entries in this project"),
    tag: list[str] = typer.Option(None, help="Match: entries having this tag (repeatable)"),
    source: str = typer.Option(None, help="Match: only entries with this source"),
    to_workspace: str = typer.Option(None, help="Move matched entries to this workspace"),
    to_project: str = typer.Option(None, help="Move matched entries to this project"),
    clear_project: bool = typer.Option(False, help="Clear the project on matched entries"),
    apply: bool = typer.Option(False, help="Apply the change (default is a dry-run preview)"),
):
    """Bulk-move entries to a new workspace/project (in-place; ids/links/embeddings preserved)."""
    logging.basicConfig(level=logging.WARNING)
    match = build_match(workspace=workspace, project=project, tags=tag, source=source)
    changes = build_changes(
        workspace=to_workspace,
        project=to_project,
        clear=["project"] if clear_project else None,
    )
    asyncio.run(_run_bulk(match, changes, apply))


@app.command()
def retag(
    workspace: str = typer.Option(None, help="Match: only entries in this workspace"),
    project: str = typer.Option(None, help="Match: only entries in this project"),
    tag: list[str] = typer.Option(None, help="Match: entries having this tag (repeatable)"),
    source: str = typer.Option(None, help="Match: only entries with this source"),
    add: list[str] = typer.Option(None, help="Add this tag to matched entries (repeatable)"),
    remove: list[str] = typer.Option(None, help="Remove this tag (repeatable)"),
    rename: str = typer.Option(None, help="Rename a tag across matched entries (old=new)"),
    apply: bool = typer.Option(False, help="Apply the change (default is a dry-run preview)"),
):
    """Bulk add/remove/rename tags on entries (in-place; ids/links/embeddings preserved)."""
    logging.basicConfig(level=logging.WARNING)
    rename_from = rename_to = None
    if rename:
        if "=" not in rename or rename.startswith("="):
            console.print("[red]--rename expects old=new[/red]")
            raise typer.Exit(1)
        rename_from, rename_to = rename.split("=", 1)
    match = build_match(workspace=workspace, project=project, tags=tag, source=source)
    changes = build_changes(
        add_tags=add,
        remove_tags=remove,
        rename_from=rename_from,
        rename_to=rename_to,
    )
    asyncio.run(_run_bulk(match, changes, apply))


@app.command()
def version():
    """Show magpie version."""
    console.print(f"magpie {__version__}")


if __name__ == "__main__":
    app()
