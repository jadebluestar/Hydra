"""
Gateway authentication helpers.

Separate from api/v1/deps.py because the gateway uses API key auth,
not JWT auth. These are two independent authentication mechanisms on
different code paths.
"""

from __future__ import annotations

from fastapi import Request

from core.exceptions import ForbiddenError, UnauthorizedError
from domain.enums.scope import APIKeyScope
from security.scopes import has_scope


def extract_api_key(request: Request) -> str:
    """
    Extract the raw API key string from Authorization: Bearer <key>.

    Raises UnauthorizedError if the header is absent or not Bearer-scheme.
    The returned string is unvalidated — call APIKeyService.verify() next.
    """
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise UnauthorizedError("Missing or invalid Authorization header")
    token = auth[len("Bearer "):].strip()
    if not token:
        raise UnauthorizedError("Missing API key")
    return token


def check_scope(granted_scopes: list[str], required_scope: str | None) -> None:
    """
    Verify the key's scopes satisfy the route's required_scope.

    None required_scope = public route, no check needed.
    Raises ForbiddenError (403) — not UnauthorizedError (401) — because
    the key IS valid (authenticated); it just lacks this scope (authorized).
    """
    if required_scope is None:
        return
    if not has_scope(granted_scopes, APIKeyScope(required_scope)):
        raise ForbiddenError(
            f"API key scope insufficient: requires '{required_scope}'"
        )
