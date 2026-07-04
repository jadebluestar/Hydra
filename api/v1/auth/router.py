"""
Auth endpoints.

All responses use consistent camelCase JSON. Token payloads follow the
OAuth2 bearer token spec shape (access_token, token_type, expires_in)
so clients can treat these tokens like standard OAuth2 tokens.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.deps import get_current_user, get_current_user_payload
from cache.client import get_redis
from core.config import Settings, get_settings
from database.session import get_db
from models.user import User
from providers.implementations.argon2_hasher import Argon2Hasher
from providers.implementations.jwt_hs256 import HS256JWTProvider
from providers.implementations.mock_email import MockEmailProvider
from repositories.user_repository import UserRepository
from schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from schemas.user import UserResponse
from services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_auth_service(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
) -> AuthService:
    """
    Construct AuthService with its concrete dependencies.

    This factory lives in the router module rather than as a Depends() chain
    because the concrete provider implementations (HS256JWTProvider, etc.)
    are an application-layer detail — the service only knows about Protocol types.

    In a future milestone this can be replaced with a DI container (e.g., lagom)
    but for now explicit construction keeps the dependency graph readable.
    """
    return AuthService(
        user_repo=UserRepository(session),
        jwt_provider=HS256JWTProvider(),
        hasher=Argon2Hasher(),
        email_provider=MockEmailProvider(),
        redis=redis,
        settings=settings,
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
)
async def register(
    body: RegisterRequest,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    svc = _build_auth_service(session, redis, settings)
    access_token, refresh_token = await svc.register(
        email=str(body.email),
        password=body.password,
        full_name=body.full_name,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and receive tokens",
)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    svc = _build_auth_service(session, redis, settings)
    access_token, refresh_token = await svc.login(
        email=str(body.email),
        password=body.password,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Exchange a refresh token for a new token pair",
)
async def refresh(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    svc = _build_auth_service(session, redis, settings)
    access_token, new_refresh_token = await svc.refresh(
        refresh_token=body.refresh_token,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Invalidate the current session",
)
async def logout(
    body: LogoutRequest,
    access_payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> None:
    svc = _build_auth_service(session, redis, settings)
    await svc.logout(
        access_payload=access_payload,
        refresh_token=body.refresh_token,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the currently authenticated user",
)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    return UserResponse.model_validate(current_user)
