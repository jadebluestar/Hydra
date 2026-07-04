"""
Async SQLAlchemy session factory.

Design decisions:
  - Single global engine and session factory, created once at startup.
  - pool_pre_ping=True: before handing a connection from the pool to a query,
    SQLAlchemy sends a lightweight "SELECT 1" to verify the connection is alive.
    This prevents "connection closed" errors after a database restart or
    cloud provider recycling idle connections.
  - expire_on_commit=False: by default SQLAlchemy expires all attributes after a
    commit, forcing a fresh SELECT the next time you access them. Since we use
    async sessions and may return Pydantic models before the session closes, we
    disable this to avoid "MissingGreenlet" errors.
  - autoflush=False: we flush explicitly when we want to. Implicit flushes
    during queries can cause surprising behavior with async code.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings

logger = structlog.get_logger(__name__)

# Module-level singletons — initialized in init_db_pool(), never touched elsewhere.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db_pool() -> None:
    """Create the connection pool. Called once during application startup."""
    global _engine, _session_factory
    settings = get_settings()

    _engine = create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        echo=settings.DEBUG,  # logs every SQL statement in debug mode
        pool_pre_ping=True,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    logger.info(
        "database.pool_ready",
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
    )


async def close_db_pool() -> None:
    """Drain the connection pool. Called during application shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        logger.info("database.pool_closed")


@asynccontextmanager
async def get_standalone_session() -> AsyncIterator[AsyncSession]:
    """
    Create a database session outside of a FastAPI request context.

    Used by background tasks (e.g., gateway request logging) that run after
    the request session is already closed. Each call creates a fresh session
    from the pool, commits on success, and rolls back on failure.
    """
    if _session_factory is None:
        raise RuntimeError("Database pool is not initialized. Was init_db_pool() called?")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncIterator[AsyncSession]:
    """
    FastAPI dependency that yields a database session for the duration of a request.

    The session is committed on success and rolled back on any exception, then
    always closed when the request completes — whether it succeeded or failed.

    Usage:
        @router.post("/things")
        async def create_thing(db: AsyncSession = Depends(get_db)):
            ...
    """
    if _session_factory is None:
        raise RuntimeError("Database pool is not initialized. Was init_db_pool() called?")

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
