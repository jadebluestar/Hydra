"""
Cache Provider interface.

Defines the contract for key/value cache operations. The current
implementation wraps Redis (Milestone 17). A future implementation
could wrap Memcached or an in-memory dict (useful in tests).

All operations are async because cache access is network I/O (to Redis).

Key design: all keys must be strings, all values must be strings.
If you need to cache structured data, serialize to JSON before calling
set() and deserialize after calling get(). This keeps the interface
simple and the cache layer unaware of serialization formats.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class CacheProvider(Protocol):
    async def get(self, key: str) -> str | None:
        """
        Get a value by key.

        Returns None if the key does not exist or has expired.
        Never raises on a cache miss.
        """
        ...

    async def set(
        self,
        key: str,
        value: str,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        """
        Set a key to a value.

        Args:
            key:         Cache key (use cache/keys.py helpers to construct).
            value:       String value to cache.
            ttl_seconds: Time-to-live. None means the key never expires.
                         Always set a TTL unless you have a specific reason
                         not to — unbounded caches cause memory issues.
        """
        ...

    async def delete(self, key: str) -> None:
        """
        Delete a key.

        No-op if the key does not exist. Never raises on a missing key.
        """
        ...

    async def exists(self, key: str) -> bool:
        """Return True if the key exists and has not expired."""
        ...

    async def increment(self, key: str, amount: int = 1) -> int:
        """
        Atomically increment a counter.

        If the key does not exist, it is created with value 0 before
        incrementing. Returns the new value.

        Used by the rate limiter to count requests in a sliding window.
        The atomic guarantee is critical — without it, concurrent requests
        could read the same value and both increment from it, allowing
        more requests than the limit.
        """
        ...
