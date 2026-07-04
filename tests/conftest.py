"""
Pytest configuration and shared fixtures.

IMPORTANT: environment variables must be set before any application module is
imported, because core/config.py reads them at the time get_settings() is first
called. Setting them here at module level (before any test file imports the app)
ensures get_settings() sees the test values when it is first invoked.
"""

import os

# ── Test environment ──────────────────────────────────────────────────────────
# These override any .env file values for the duration of the test run.
# Use DB index 1 for Redis so tests don't collide with a running dev server.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://hydra:hydra_secret@localhost:5432/hydra_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-that-is-at-least-32-characters-long",
)
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DEBUG", "false")

# ── App imports (after env is set) ────────────────────────────────────────────
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from core.config import get_settings
from main import create_app


@pytest.fixture(scope="session", autouse=True)
def clear_settings_cache() -> None:
    """Force get_settings() to re-read from the patched environment."""
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    """
    HTTP test client that drives the full ASGI app — middleware, lifespan,
    dependency injection, exception handlers — without starting a real server.

    ASGITransport triggers the lifespan context manager, so init_db_pool() and
    init_redis_pool() run. Because pool creation is lazy (no actual connections
    until a query fires), tests that don't hit the DB or Redis work without
    any infrastructure.
    """
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac
