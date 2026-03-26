"""FastAPI application with lifespan."""

import hashlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from magpie.config.settings import Settings
from magpie.db.database import Database
from magpie.embeddings.base import EmbeddingProvider
from magpie.embeddings.openai import OpenAIEmbeddings
from magpie.mcp.server import init_mcp, mcp_server
from magpie.server.routes import auth, entries, health, keys, orgs

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}
AUTH_PATHS = {"/api/auth/send-code", "/api/auth/verify-code", "/api/auth/me"}

# Store the shared MCP app instance
_mcp_http = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _mcp_http

    settings = Settings()
    app.state.settings = settings

    # Database
    db = await Database.connect(settings.database_url)
    app.state.db = db

    # Embeddings
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

    # Initialize MCP
    init_mcp(db, embedder)
    _mcp_http = mcp_server.streamable_http_app()

    async with _mcp_http.router.lifespan_context(_mcp_http):
        logger.info("magpie started on %s:%d", settings.host, settings.port)
        yield

    if embedder:
        await embedder.close()
    await db.close()
    _mcp_http = None
    logger.info("magpie stopped")


def _create_inner_app() -> FastAPI:
    """Create the FastAPI app without auth middleware (auth is in the ASGI wrapper)."""
    app = FastAPI(title="magpie", lifespan=lifespan)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(entries.router)
    app.include_router(keys.router)
    app.include_router(orgs.router)

    # Serve web UI
    web_dist = None
    for candidate in [
        Path("web/dist"),
        Path(__file__).parent.parent.parent / "web" / "dist",
    ]:
        if candidate.exists() and (candidate / "index.html").exists():
            web_dist = candidate
            break

    if web_dist:
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/{path:path}")
        async def spa_fallback(path: str):
            file = web_dist / path
            if file.is_file():
                return FileResponse(file)
            return FileResponse(web_dist / "index.html")

    return app


def create_app():
    """Create the combined ASGI app with auth + MCP routing."""
    inner = _create_inner_app()

    async def app(scope, receive, send):
        path = scope.get("path", "")

        # Lifespan — delegate to FastAPI
        if scope["type"] == "lifespan":
            await inner(scope, receive, send)
            return

        # /mcp — delegate directly to MCP app (bypasses middleware)
        if path == "/mcp":
            # Auth check for MCP
            if not await _check_auth(scope, inner):
                response = JSONResponse(
                    status_code=401, content={"error": "Unauthorized"}
                )
                await response(scope, receive, send)
                return
            await _mcp_http(scope, receive, send)
            return

        # Everything else — FastAPI (with its own auth via middleware)
        await inner(scope, receive, send)

    # Add auth middleware to the inner FastAPI app
    from magpie.server.auth import AuthMiddleware
    inner.add_middleware(AuthMiddleware)

    return app


async def _check_auth(scope, app) -> bool:
    """Check auth for MCP requests by examining headers."""
    headers = dict(scope.get("headers", []))
    auth_header = headers.get(b"authorization", b"").decode()

    if not auth_header.startswith("Bearer "):
        return False

    token = auth_header[7:]
    settings = app.state.settings

    # Static key
    if settings.api_key and token == settings.api_key:
        return True

    # Per-user key
    db = app.state.db
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    key_record = await db.get_api_key_by_hash(key_hash)
    if key_record:
        await db.touch_api_key(key_record["id"])
        return True

    return False
