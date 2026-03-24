"""FastAPI application with lifespan."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from magpie.config.settings import Settings
from magpie.db.database import Database
from magpie.embeddings.base import EmbeddingProvider
from magpie.embeddings.openai import OpenAIEmbeddings
from magpie.mcp.server import init_mcp, mcp_server
from magpie.server.auth import AuthMiddleware
from magpie.server.routes import entries, health, keys

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.settings = settings

    # Database
    db = await Database.connect(settings.database_url)
    app.state.db = db

    # Embeddings (optional — needs both API key and pgvector in DB)
    embedder: EmbeddingProvider | None = None
    if settings.openai_api_key and db.has_vectors:
        embedder = OpenAIEmbeddings(
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
            dims=settings.embedding_dimensions,
        )
        logger.info("Embeddings enabled (%s)", settings.embedding_model)
    elif settings.openai_api_key and not db.has_vectors:
        logger.info("MAGPIE_OPENAI_API_KEY set but pgvector not available — keyword search only")
    else:
        logger.info("No MAGPIE_OPENAI_API_KEY — keyword search only")
    app.state.embedder = embedder

    # Initialize MCP server with db + embedder
    init_mcp(db, embedder)

    logger.info("magpie started on %s:%d", settings.host, settings.port)

    yield

    if embedder:
        await embedder.close()
    await db.close()
    logger.info("magpie stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="magpie", lifespan=lifespan)

    # API routes
    app.include_router(health.router)
    app.include_router(entries.router)
    app.include_router(keys.router)

    # Mount MCP server at /mcp
    app.mount("/mcp", mcp_server.streamable_http_app())

    # Auth middleware
    app.add_middleware(AuthMiddleware)

    # Serve web UI from built assets (if available)
    # Check multiple locations: relative to working dir (Docker), or relative to package
    web_dist = None
    for candidate in [
        Path("web/dist"),  # Docker working dir /app
        Path(__file__).parent.parent.parent / "web" / "dist",  # relative to package
    ]:
        if candidate.exists() and (candidate / "index.html").exists():
            web_dist = candidate
            break
    if web_dist:
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/{path:path}")
        async def spa_fallback(path: str):
            """Serve index.html for all non-API routes (SPA routing)."""
            file = web_dist / path
            if file.is_file():
                return FileResponse(file)
            return FileResponse(web_dist / "index.html")

    return app
