"""
In-memory prefix trie for O(k) path routing, where k is the path segment count.

Used by the gateway hot path instead of a DB query per request.
The trie for each project is loaded once on first access and stays in memory
until invalidated (route config changes).

Segment boundary guarantee:
    Route "/api" does NOT match request "/apikeys"
    because "apikeys" != "api" at the first path segment.
    String-prefix matching would get this wrong; trie matching gets it right.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class RouteMatch:
    """
    Session-free snapshot of a route + its upstream configuration.

    Stored in the trie instead of SQLAlchemy models to avoid session-affinity
    issues: ORM objects are scoped to a DB session; this dataclass lives
    safely in process memory for the lifetime of the process.
    """

    route_id: uuid.UUID
    path_prefix: str
    upstream_base_url: str
    upstream_timeout_seconds: int
    upstream_retries: int
    methods: list[str]
    required_scope: str | None
    strip_prefix: bool
    rate_limit_rpm: int | None
    is_active: bool
    # upstream_id is used by the circuit breaker — two routes to the same
    # upstream share one circuit so the breaker reflects the upstream's health,
    # not an individual route's. Default allows existing tests to omit the field.
    upstream_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class _TrieNode:
    children: dict[str, _TrieNode] = field(default_factory=dict)
    route: RouteMatch | None = None


class PathTrie:
    """
    Prefix trie for HTTP path routing.

    Insert: split path_prefix by '/', walk/create nodes, store RouteMatch at leaf.
    Match:  walk the same nodes for the request path; return the deepest match found.

    Longest-prefix wins — a request to /api/v1/users matches /api/v1 (not /api)
    when both are registered, because we keep updating `best` as we walk deeper.
    """

    def __init__(self) -> None:
        self._root = _TrieNode()

    def insert(self, match: RouteMatch) -> None:
        segments = [s for s in match.path_prefix.split("/") if s]
        node = self._root
        if not segments:  # root path "/"
            node.route = match
            return
        for seg in segments:
            if seg not in node.children:
                node.children[seg] = _TrieNode()
            node = node.children[seg]
        node.route = match

    def match(self, path: str) -> RouteMatch | None:
        """
        Return the longest-prefix matching route for a request path.
        Returns None if no registered route covers this path.
        """
        segments = [s for s in path.split("/") if s]
        node = self._root
        best: RouteMatch | None = node.route  # root "/" catches everything if present
        for seg in segments:
            if seg not in node.children:
                break
            node = node.children[seg]
            if node.route is not None:
                best = node.route
        return best

    def remove(self, path_prefix: str) -> None:
        """Remove a route by path prefix. No-op if the prefix is not registered."""
        segments = [s for s in path_prefix.split("/") if s]
        node = self._root
        if not segments:
            node.route = None
            return
        for seg in segments:
            if seg not in node.children:
                return
            node = node.children[seg]
        node.route = None

    @property
    def is_empty(self) -> bool:
        return self._root.route is None and not self._root.children
