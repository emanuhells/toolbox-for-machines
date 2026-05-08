"""FastAPI application — main entry point for the Toolbox service."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from toolbox.cache import cache
from toolbox.config import settings
from toolbox.http_client import close_http_client, get_http_client, init_http_client

log = logging.getLogger("toolbox")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage shared HTTP client and MCP server lifecycle."""
    init_http_client(timeout=settings.fetch_timeout_seconds)

    async def _cache_cleanup_loop():
        """Background task: clean expired cache entries every 10 minutes."""
        # Startup cleanup
        try:
            removed = cache.cleanup()
            if removed > 0:
                log.info("Startup cache cleanup: removed %d expired entries", removed)
                if removed > 100:
                    cache.vacuum()
                    log.info("Ran VACUUM after large cleanup")
        except Exception as e:
            log.warning("Startup cache cleanup failed: %s", e)

        while True:
            await asyncio.sleep(600)  # 10 minutes
            try:
                removed = cache.cleanup()
                if removed > 0:
                    log.info("Cache cleanup: removed %d expired entries", removed)
            except Exception as e:
                log.warning("Cache cleanup failed: %s", e)

    # Start background task, cancel on shutdown
    cleanup_task = asyncio.create_task(_cache_cleanup_loop())

    if settings.mcp_enabled:
        from toolbox.mcp_server import mcp
        # Initialize the MCP session manager within our lifespan
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except asyncio.CancelledError:
                    pass
                await close_http_client()
    else:
        try:
            yield
        finally:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
            await close_http_client()


app = FastAPI(
    title="Toolbox",
    description="Self-contained tool service for AI agents",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Require a valid API key when API_KEY is set."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        if not settings.api_key:
            return await call_next(request)
        auth_header = request.headers.get("Authorization", "")
        x_api_key = request.headers.get("X-API-Key", "")
        bearer = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
        if bearer == settings.api_key or x_api_key == settings.api_key:
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})


app.add_middleware(APIKeyMiddleware)


# ── Health check ──────────────────────────────────────────────────────────────


@app.get("/healthz")
async def healthz():
    """Liveness check for the API itself."""
    http = get_http_client()
    backends = {}

    # Check SearXNG
    try:
        r = await http.get(f"{settings.searxng_url}/", timeout=3)
        backends["searxng"] = "healthy" if r.status_code == 200 else "unhealthy"
    except Exception:
        backends["searxng"] = "unreachable"

    # Check Camoufox
    try:
        r = await http.get(f"{settings.camoufox_url}/healthz", timeout=5)
        backends["camoufox"] = "healthy" if r.status_code == 200 else "unhealthy"
    except Exception:
        backends["camoufox"] = "unreachable"

    # Check Whisper
    try:
        r = await http.get(f"{settings.whisper_url}/health", timeout=3)
        backends["whisper"] = "healthy" if r.status_code == 200 else "unhealthy"
    except Exception:
        backends["whisper"] = "unreachable"

    # Check LLM
    try:
        headers = {}
        if settings.llm_api_key:
            headers["Authorization"] = f"Bearer {settings.llm_api_key}"
        r = await http.get(f"{settings.llm_url}/models", headers=headers, timeout=5)
        backends["llm"] = "healthy" if r.status_code == 200 else "unhealthy"
    except Exception:
        backends["llm"] = "unreachable"

    status = "ok" if all(v == "healthy" for v in backends.values()) else "degraded"
    return {"status": status, "backends": backends}


# ── Mount tool routers ────────────────────────────────────────────────────────

from toolbox.skills import router as skills_router  # noqa: E402
from toolbox.tools.describe import router as describe_router  # noqa: E402
from toolbox.tools.extract import router as extract_router  # noqa: E402
from toolbox.tools.fetch import router as fetch_router  # noqa: E402
from toolbox.tools.harness_prompt import router as harness_prompt_router  # noqa: E402
from toolbox.tools.search import router as search_router  # noqa: E402
from toolbox.tools.summarize import router as summarize_router  # noqa: E402
from toolbox.tools.transcribe import router as transcribe_router  # noqa: E402

app.include_router(search_router, prefix="/v1")
app.include_router(fetch_router, prefix="/v1")
app.include_router(describe_router, prefix="/v1")
app.include_router(transcribe_router, prefix="/v1")
app.include_router(summarize_router, prefix="/v1")
app.include_router(extract_router, prefix="/v1")
app.include_router(skills_router, prefix="/v1")
app.include_router(harness_prompt_router, prefix="/v1")


# ── Mount MCP server ─────────────────────────────────────────────────────────

if settings.mcp_enabled:
    from starlette.applications import Starlette  # noqa: E402
    from starlette.routing import Route  # noqa: E402

    from toolbox.mcp_server import mcp  # noqa: E402

    # Call streamable_http_app() to initialize the session manager,
    # but we won't use the returned Starlette app (it has its own lifespan
    # that conflicts with ours). Instead we mount a minimal app.
    _full_mcp_app = mcp.streamable_http_app()
    # Now session_manager is initialized, create our own minimal mount
    from mcp.server.fastmcp.server import StreamableHTTPASGIApp  # noqa: E402
    mcp_handler = StreamableHTTPASGIApp(mcp.session_manager)
    mcp_app = Starlette(
        routes=[Route("/", endpoint=mcp_handler)],
    )
    app.mount("/mcp", mcp_app)
