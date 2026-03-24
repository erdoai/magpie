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
        console.print("[red]MAGPIE_DATABASE_URL is not set[/red]")
        raise typer.Exit(1)

    async def _run():
        pool = await asyncpg.create_pool(settings.database_url)
        await run_migrations(pool)
        await pool.close()
        console.print("[green]Migrations applied successfully[/green]")

    asyncio.run(_run())


@app.command()
def version():
    """Show magpie version."""
    from magpie.__version__ import __version__

    console.print(f"magpie {__version__}")


if __name__ == "__main__":
    app()
