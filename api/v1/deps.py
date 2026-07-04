"""
FastAPI dependencies for the v1 API.

Dependencies are composable functions that FastAPI resolves via Depends().
Each endpoint declares what it needs; FastAPI builds the dependency graph,
calls each function once per request, and injects the results.

Key dependency chain for authenticated endpoints:

    endpoint(user: User = Depends(get_current_user))
        → get_current_user(
              token: str = Depends(http_bearer),
              session: AsyncSession = Depends(get_db),
              redis: Redis = Depends(get_redis),
          )
              → validates JWT, checks revocation, loads User from DB
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from cache.client import get_redis
from core.exceptions import UnauthorizedError
from database.session import get_db
from models.user import User
from providers.implementations.jwt_hs256 import HS256JWTProvider
from repositories.user_repository import UserRepository

# HTTPBearer extracts the "Bearer <token>" value from the Authorization header.
# auto_error=False lets us raise our own UnauthorizedError instead of FastAPI's
# default 403 — consistent error format across the API.
_http_bearer = HTTPBearer(auto_error=False)


def _get_jwt_provider() -> HS256JWTProvider:
    """JWT provider singleton — safe to reuse across requests (stateless)."""
    return HS256JWTProvider()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer),
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    jwt_provider: HS256JWTProvider = Depends(_get_jwt_provider),
) -> User:
    """
    Extract, validate, and return the authenticated user.

    Steps:
      1. Extract Bearer token from Authorization header
      2. Decode and verify JWT signature + expiry
      3. Check the token's JTI is not in the revocation set (logout)
      4. Load the user from the database

    Raises:
        UnauthorizedError → 401 if any step fails.
    """
    if not credentials:
        raise UnauthorizedError("Authorization header is required")

    token = credentials.credentials

    payload: dict[str, Any] = jwt_provider.decode(token)

    if payload.get("type") != "access":
        raise UnauthorizedError("Token is not an access token")

    jti = payload.get("jti")
    if jti:
        from cache.keys import revoked_token_key

        revoked = await redis.get(revoked_token_key(jti))
        if revoked is not None:
            raise UnauthorizedError("Token has been revoked")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise UnauthorizedError("Token missing subject claim")

    import uuid

    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(uuid.UUID(user_id_str))

    if not user or not user.is_active:
        raise UnauthorizedError("Account not found or deactivated")

    return user


async def get_current_user_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer),
    jwt_provider: HS256JWTProvider = Depends(_get_jwt_provider),
) -> dict[str, Any]:
    """
    Decode the JWT and return its payload without loading the user from DB.

    Used by logout — we need the JTI to revoke, but don't need the full
    User object. Saves one DB query on the logout path.
    """
    if not credentials:
        raise UnauthorizedError("Authorization header is required")
    return jwt_provider.decode(credentials.credentials)
