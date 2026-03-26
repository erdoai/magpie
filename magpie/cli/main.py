"""Magpie CLI — knowledge store with dual search."""

import logging

import typer
from rich.console import Console

app = typer.Typer(help="magpie — knowledge store with semantic + keyword search")
console = Console()


@app.command()
def serve(
    host: str = typer.Option(None, help="Override MAGPIE_HOST"),
    port: int = typer.Option(None, help="Override MAGPIE_PORT"),
):
    """Start the magpie server (REST + MCP)."""
    import os

    import uvicorn

    from magpie.config.settings import Settings

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
    import asyncio

    import asyncpg

    from magpie.config.settings import Settings
    from magpie.db.migrate import run_migrations

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
):
    """Import knowledge from external sources."""
    import asyncio
    from pathlib import Path

    from magpie.config.settings import Settings
    from magpie.db.database import Database

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")

    settings = Settings()
    if not settings.database_url:
        console.print("[red]DATABASE_URL is not set[/red]")
        raise typer.Exit(1)

    async def _run():
        db = await Database.connect(settings.database_url)

        embedder = None
        if settings.openai_api_key:
            from magpie.embeddings.openai import OpenAIEmbeddings

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
                        db, embedder, md_file, workspace, source="claude-code"
                    )

        elif source == "markdown":
            # Import markdown files from a directory
            base = Path(path) if path else Path(".")
            for md_file in sorted(base.rglob("*.md")):
                count += await _import_markdown_file(
                    db, embedder, md_file, workspace, source="markdown"
                )

        else:
            console.print(f"[red]Unknown source: {source}. Use 'claude' or 'markdown'.[/red]")
            raise typer.Exit(1)

        if embedder:
            await embedder.close()
        await db.close()
        console.print(f"[green]Imported {count} entries into workspace '{workspace}'[/green]")

    asyncio.run(_run())


async def _import_markdown_file(db, embedder, file_path, workspace, source):
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

    await db.create_entry(
        title=title,
        content=text,
        category=category,
        tags=tags,
        source=source,
        embedding=embedding,
        workspace=workspace,
    )
    console.print(f"  Imported: {title}")
    return 1


@app.command()
def version():
    """Show magpie version."""
    from magpie.__version__ import __version__

    console.print(f"magpie {__version__}")


if __name__ == "__main__":
    app()
