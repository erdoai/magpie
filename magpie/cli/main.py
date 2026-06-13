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

from magpie.__version__ import __version__
from magpie.attachments import handle_for, infer_kind, storage_key_for
from magpie.bundle import load_manifest, scan_collections, scan_entries
from magpie.config.settings import Settings
from magpie.db.database import Database
from magpie.db.migrate import run_migrations
from magpie.embeddings.openai import OpenAIEmbeddings
from magpie.links import sync_entry_links
from magpie.manifest import check_drift
from magpie.storage import create_storage

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
    category = "resource"
    tags = []

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            text = parts[2].strip()

            for line in frontmatter.strip().split("\n"):
                if line.startswith("name:"):
                    title = line.split(":", 1)[1].strip().strip('"')
                elif line.startswith("type:"):
                    t = line.split(":", 1)[1].strip().strip('"')
                    if t in ("project", "area", "resource"):
                        category = t
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
        category=category,
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
    col_result = scan_collections(directory)
    manifest, manifest_err = load_manifest(directory)
    file_errors = list(result.errors) + list(col_result.errors)
    if manifest_err:
        file_errors.append(manifest_err)
    if file_errors:
        console.print(f"[red]Refusing to push — {len(file_errors)} file(s) off-spec:[/red]")
        for err in file_errors:
            console.print(f"  [red]{err.path}[/red]: {err.message}")
        raise typer.Exit(1)

    # Anti-drift: reject undeclared/near-duplicate collections before any writes.
    drift = check_drift(col_result.collections, manifest)
    for warning in drift.warnings:
        console.print(f"  [yellow]warning[/yellow]: {warning}")
    if not drift.ok:
        console.print(f"[red]Refusing to push — {len(drift.errors)} drift issue(s):[/red]")
        for err in drift.errors:
            console.print(f"  [red]{err}[/red]")
        raise typer.Exit(1)

    if not result.entries and not col_result.collections:
        console.print("[yellow]No entries or collections found in bundle.[/yellow]")
        return

    async def _run():
        db = await Database.connect(settings.database_url)

        # Pre-flight: a repo collection must not clobber a live server-canonical
        # store of the same slug. Detect before writing anything.
        conflicts = []
        existing_cols = {}
        for col in col_result.collections:
            found = await db.find_collection(
                col.slug, org_id=org_id, workspace=workspace, project=project
            )
            if found and found.get("org_id") == org_id:
                if found.get("source") != "repo":
                    conflicts.append(col.slug)
                existing_cols[col.slug] = found
        if conflicts:
            await db.close()
            console.print(
                "[red]Refusing to push — these collections already exist as "
                "server-canonical (live) stores:[/red]"
            )
            for slug in conflicts:
                console.print(f"  [red]{slug}[/red]: edit it via the API/agent, not the repo")
            raise typer.Exit(1)

        embedder = None
        if settings.openai_api_key:
            embedder = OpenAIEmbeddings(
                api_key=settings.openai_api_key,
                model=settings.embedding_model,
                dims=settings.embedding_dimensions,
            )

        created = updated = 0
        for entry in result.entries:
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
            updated += was_updated
            created += not was_updated
            verb = "updated" if was_updated else "created"
            console.print(f"  {verb}: {entry.path}")

        doc_count = 0
        for col in col_result.collections:
            existing = existing_cols.get(col.slug)
            if existing:
                col_id = existing["id"]
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
                doc_count += 1
            console.print(f"  collection: {col.slug} ({len(col.documents)} docs)")

        if embedder:
            await embedder.close()
        await db.close()
        console.print(
            f"[green]Pushed {len(result.entries)} entries "
            f"({created} created, {updated} updated) and {len(col_result.collections)} "
            f"repo collections ({doc_count} docs) into '{workspace}'[/green]"
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

        entry = await db.get_entry(entry_id)
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


@app.command()
def version():
    """Show magpie version."""
    console.print(f"magpie {__version__}")


if __name__ == "__main__":
    app()
