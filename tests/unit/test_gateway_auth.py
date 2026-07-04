"""Unit tests for gateway authentication helpers."""

from __future__ import annotations

import pytest
from fastapi import Request

from core.exceptions import ForbiddenError, UnauthorizedError
from gateway.auth import check_scope, extract_api_key


def _request(auth_header: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if auth_header is not None:
        headers.append((b"authorization", auth_header.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/gateway/api/users",
        "headers": headers,
        "query_string": b"",
    }
    return Request(scope=scope)


class TestExtractApiKey:
    def test_valid_bearer_returns_key(self) -> None:
        req = _request("Bearer hk_live_abc123deadbeef")
        assert extract_api_key(req) == "hk_live_abc123deadbeef"

    def test_missing_header_raises_unauthorized(self) -> None:
        req = _request(None)
        with pytest.raises(UnauthorizedError):
            extract_api_key(req)

    def test_non_bearer_scheme_raises_unauthorized(self) -> None:
        req = _request("Basic dXNlcjpwYXNz")
        with pytest.raises(UnauthorizedError):
            extract_api_key(req)

    def test_bearer_without_token_raises_unauthorized(self) -> None:
        req = _request("Bearer ")
        with pytest.raises(UnauthorizedError):
            extract_api_key(req)

    def test_empty_authorization_header_raises_unauthorized(self) -> None:
        req = _request("")
        with pytest.raises(UnauthorizedError):
            extract_api_key(req)

    def test_key_is_stripped_of_whitespace(self) -> None:
        req = _request("Bearer   hk_live_trimmed   ")
        assert extract_api_key(req) == "hk_live_trimmed"


class TestCheckScope:
    def test_no_required_scope_always_passes(self) -> None:
        check_scope([], None)
        check_scope(["gateway:read"], None)

    def test_exact_scope_match_passes(self) -> None:
        check_scope(["gateway:read"], "gateway:read")

    def test_missing_scope_raises_forbidden(self) -> None:
        with pytest.raises(ForbiddenError):
            check_scope(["gateway:read"], "gateway:write")

    def test_empty_scopes_raises_forbidden(self) -> None:
        with pytest.raises(ForbiddenError):
            check_scope([], "gateway:read")

    def test_write_implies_read(self) -> None:
        check_scope(["gateway:write"], "gateway:read")

    def test_admin_covers_gateway_write(self) -> None:
        check_scope(["admin"], "gateway:write")

    def test_admin_covers_analytics_read(self) -> None:
        check_scope(["admin"], "analytics:read")

    def test_unrelated_scope_raises_forbidden(self) -> None:
        with pytest.raises(ForbiddenError):
            check_scope(["analytics:read"], "gateway:read")
