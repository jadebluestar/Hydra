"""
Redis connection pool and FastAPI dependency.

We use a single shared ConnectionPool across the process. Redis is thread-safe
and connection-pool-safe, so async tasks can share the same client without
locking.

decode_responses=True means Redis returns Python str instead of bytes. Every
key and value stored through this client is a UTF-8 string. If you ever need
to store raw binary data (e.g., serialized protobuf), create a separate client
with decode_responses=False.
"""

import structlog
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool

from core.config import get_settings

logger = structlog.get_logger(__name__)

_pool: ConnectionPool | None = None
_client: Redis | None = None  # type: ignore[type-arg]


async def init_redis_pool() -> None:
    """Create the Redis connection pool. Called once during application startup."""
    global _pool, _client
    settings = get_settings()

    _pool = ConnectionPool.from_url(
        settings.REDIS_URL,
        max_connections=20,
        decode_responses=True,
    )
    _client = Redis(connection_pool=_pool)

    # Connectivity is validated lazily by the /ready endpoint, not here.
    # This keeps startup fast and allows the app to start even if Redis is
    # briefly unavailable (it will fail /ready checks until Redis comes up).
    logger.info("redis.pool_ready")


async def close_redis_pool() -> None:
    """Close the Redis connection pool. Called during application shutdown."""
    global _client, _pool
    if _client is not None:
        await _client.aclose()
    if _pool is not None:
        await _pool.aclose()
    logger.info("redis.pool_closed")


async def get_redis() -> Redis:  # type: ignore[type-arg]
    """
    FastAPI dependency that returns the shared Redis client.

    Usage:
        @router.get("/things")
        async def list_things(redis: Redis = Depends(get_redis)):
            cached = await redis.get("hydra:things:all")
    """
    if _client is None:
        raise RuntimeError("Redis pool is not initialized. Was init_redis_pool() called?")
    return _client
