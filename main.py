"""
Application factory.

Using a factory function (create_app) instead of a bare module-level `app`
gives us:
  - Full control over initialization order (logging → config → middleware → routes)
  - Easy testing: create_app() in test fixtures produces an isolated instance
  - No import-time side effects from the top-level module

The lifespan context manager (introduced in FastAPI 0.93) replaces the older
@app.on_event("startup") / @app.on_event("shutdown") pattern. It guarantees
cleanup runs even if startup partially fails.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.gateway.router import router as gateway_router
from api.v1 import api_v1_router, health_router_root
from cache.client import close_redis_pool, init_redis_pool
from core.config import get_settings
from core.exceptions import configure_exception_handlers
from core.logging import configure_logging
from database.session import close_db_pool, init_db_pool
from gateway.state import GatewayState
from middleware.correlation import CorrelationIDMiddleware
from middleware.logging import LoggingMiddleware
from middleware.request_id import RequestIDMiddleware

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(
        "hydra.starting",
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
    )

    await init_db_pool()
    await init_redis_pool()

    # Shared HTTP client for proxying upstream requests.
    # Single instance = connection pool reuse across all gateway requests.
    http_client = httpx.AsyncClient()
    app.state.gateway = GatewayState(http_client=http_client)

    logger.info("hydra.ready")
    yield  # ← application serves requests between here and the next line

    logger.info("hydra.stopping")
    await http_client.aclose()
    await close_redis_pool()
    await close_db_pool()
    logger.info("hydra.stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    configure_logging(
        debug=settings.DEBUG,
        json_logs=settings.APP_ENV != "development",
    )

    app = FastAPI(
        title="Hydra",
        description="Production-grade API Gateway and Developer Platform",
        version=settings.APP_VERSION,
        # Disable interactive docs in production — they expose your API schema.
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Middleware ─────────────────────────────────────────────────────────────
    # add_middleware() inserts at position 0 each time, so the LAST call here
    # becomes the OUTERMOST layer (first to receive a request).
    #
    # Desired request order: RequestID → Correlation → Logging → CORS → routes
    # Therefore register in REVERSE order:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(CorrelationIDMiddleware)
    app.add_middleware(RequestIDMiddleware)  # outermost — runs first on request

    # ── Exception Handlers ────────────────────────────────────────────────────
    configure_exception_handlers(app)

    # ── Routes ───────────────────────────────────────────────────────────────
    # Health endpoints at root so Kubernetes probes work without path prefix
    app.include_router(health_router_root)

    # All versioned API routes under /api/v1
    app.include_router(api_v1_router, prefix="/api/v1")

    # Gateway proxy — all methods, all paths under /gateway/
    # Separate from the management API: /api/v1 = control plane, /gateway = data plane
    app.include_router(gateway_router, prefix="/gateway")

    # Request playground — static Postman-like UI, served at /playground.
    # html=True serves index.html for the directory root.
    app.mount("/playground", StaticFiles(directory="web/playground", html=True), name="playground")

    return app


# Module-level app instance for uvicorn: `uvicorn main:app`
app = create_app()
