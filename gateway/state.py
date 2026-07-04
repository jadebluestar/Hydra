"""
GatewayState — per-process runtime state for the gateway proxy.

Holds:
  - One PathTrie per project (lazy-loaded, evicted on route change)
  - One shared httpx.AsyncClient for upstream requests

Lifecycle: created in main.py's lifespan(), lives for the process lifetime.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import httpx

from gateway.trie import PathTrie, RouteMatch


class GatewayState:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http_client = http_client
        self._tries: dict[uuid.UUID, PathTrie] = {}
        self._lock = asyncio.Lock()

    @property
    def http_client(self) -> httpx.AsyncClient:
        return self._http_client

    async def get_trie(
        self,
        project_id: uuid.UUID,
        *,
        loader: Callable[[], Awaitable[list[RouteMatch]]],
    ) -> PathTrie:
        """
        Return the cached PathTrie for a project, building it via `loader` if absent.

        Double-checked locking: the fast path (cache hit) avoids the lock entirely.
        On a miss, we acquire the lock and check again — a concurrent request may
        have already loaded the trie while we were waiting.

        `loader` is only awaited when the trie is genuinely absent, so the caller
        (which owns the DB session) can fetch routes without wasting a DB call on
        cache hits.
        """
        if project_id in self._tries:
            return self._tries[project_id]

        async with self._lock:
            if project_id in self._tries:  # re-check under lock
                return self._tries[project_id]

            route_matches = await loader()
            trie = PathTrie()
            for match in route_matches:
                trie.insert(match)
            self._tries[project_id] = trie
            return trie

    def invalidate(self, project_id: uuid.UUID) -> None:
        """
        Evict the cached trie for a project.

        Called after any route or upstream mutation so the next gateway
        request reloads fresh config from the DB.
        """
        self._tries.pop(project_id, None)

    def invalidate_all(self) -> None:
        self._tries.clear()
