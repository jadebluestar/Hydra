"""Unit tests for the PathTrie — pure Python, no async, no DB."""

from __future__ import annotations

import uuid

from gateway.trie import PathTrie, RouteMatch


def _route(path: str, **kwargs: object) -> RouteMatch:
    return RouteMatch(
        route_id=uuid.uuid4(),
        path_prefix=path,
        upstream_base_url=kwargs.get("upstream_base_url", "http://upstream:8080"),  # type: ignore[arg-type]
        upstream_timeout_seconds=30,
        upstream_retries=3,
        methods=kwargs.get("methods", []),  # type: ignore[arg-type]
        required_scope=kwargs.get("required_scope", None),  # type: ignore[arg-type]
        strip_prefix=True,
        rate_limit_rpm=None,
        is_active=True,
    )


class TestPathTrieBasics:
    def test_empty_trie_returns_none(self) -> None:
        assert PathTrie().match("/api") is None

    def test_exact_match(self) -> None:
        trie = PathTrie()
        r = _route("/api/users")
        trie.insert(r)
        assert trie.match("/api/users") is r

    def test_prefix_match(self) -> None:
        trie = PathTrie()
        r = _route("/api")
        trie.insert(r)
        assert trie.match("/api/users/123") is r

    def test_no_match_returns_none(self) -> None:
        trie = PathTrie()
        trie.insert(_route("/api"))
        assert trie.match("/other") is None


class TestPathTrieLongestPrefix:
    def test_longest_prefix_wins(self) -> None:
        trie = PathTrie()
        short = _route("/api")
        long_ = _route("/api/v1")
        trie.insert(short)
        trie.insert(long_)
        result = trie.match("/api/v1/users")
        assert result is long_

    def test_shorter_matches_when_deeper_segment_differs(self) -> None:
        trie = PathTrie()
        short = _route("/api")
        long_ = _route("/api/v1")
        trie.insert(short)
        trie.insert(long_)
        # /api/v2 matches /api, not /api/v1
        assert trie.match("/api/v2/users") is short

    def test_insert_order_does_not_affect_longest_prefix(self) -> None:
        trie = PathTrie()
        long_ = _route("/api/v1/users")
        short = _route("/api/v1")
        trie.insert(long_)  # insert longer first
        trie.insert(short)
        assert trie.match("/api/v1/users/123") is long_


class TestPathTrieSegmentBoundary:
    def test_partial_segment_does_not_match(self) -> None:
        # "/api" must NOT match "/apikeys" — segment boundary check
        trie = PathTrie()
        trie.insert(_route("/api"))
        assert trie.match("/apikeys") is None

    def test_api_v1_does_not_match_api_v10(self) -> None:
        trie = PathTrie()
        trie.insert(_route("/api/v1"))
        assert trie.match("/api/v10/users") is None

    def test_segment_must_match_fully(self) -> None:
        trie = PathTrie()
        trie.insert(_route("/users"))
        assert trie.match("/users-admin") is None


class TestPathTrieRootPath:
    def test_root_matches_any_path(self) -> None:
        trie = PathTrie()
        r = _route("/")
        trie.insert(r)
        assert trie.match("/anything") is r
        assert trie.match("/deep/nested/path") is r

    def test_specific_route_wins_over_root(self) -> None:
        trie = PathTrie()
        root = _route("/")
        specific = _route("/api")
        trie.insert(root)
        trie.insert(specific)
        assert trie.match("/api/users") is specific
        assert trie.match("/other") is root


class TestPathTrieMultipleRoutes:
    def test_sibling_routes_do_not_interfere(self) -> None:
        trie = PathTrie()
        users = _route("/users")
        orders = _route("/orders")
        trie.insert(users)
        trie.insert(orders)
        assert trie.match("/users/123") is users
        assert trie.match("/orders/456") is orders

    def test_deep_nested_routes(self) -> None:
        trie = PathTrie()
        r1 = _route("/api/v1/users")
        r2 = _route("/api/v1/orders")
        r3 = _route("/api/v2/users")
        for r in [r1, r2, r3]:
            trie.insert(r)
        assert trie.match("/api/v1/users/123") is r1
        assert trie.match("/api/v1/orders/456") is r2
        assert trie.match("/api/v2/users/789") is r3


class TestPathTrieRemove:
    def test_remove_clears_route(self) -> None:
        trie = PathTrie()
        r = _route("/api")
        trie.insert(r)
        assert trie.match("/api/users") is r
        trie.remove("/api")
        assert trie.match("/api/users") is None

    def test_remove_does_not_affect_sibling(self) -> None:
        trie = PathTrie()
        r1 = _route("/api")
        r2 = _route("/other")
        trie.insert(r1)
        trie.insert(r2)
        trie.remove("/api")
        assert trie.match("/other/path") is r2

    def test_remove_deeper_still_matches_parent(self) -> None:
        trie = PathTrie()
        parent = _route("/api")
        child = _route("/api/v1")
        trie.insert(parent)
        trie.insert(child)
        trie.remove("/api/v1")
        # After removing /api/v1, /api/v1/users should fall back to /api
        assert trie.match("/api/v1/users") is parent

    def test_remove_nonexistent_is_noop(self) -> None:
        trie = PathTrie()
        trie.remove("/nonexistent")  # should not raise
