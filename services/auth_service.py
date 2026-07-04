"""
Auth Service — registration, login, token refresh, logout.

Owns the complete authentication lifecycle. Depends on:
  - UserRepository     (DB access)
  - JWTProvider        (encode/decode tokens)
  - HashingProvider    (hash and verify passwords)
  - EmailProvider      (send verification email)
  - Redis              (refresh token storage, access token revocation)
  - Settings           (TTL values, app metadata)
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from redis.asyncio import Redis

from cache.keys import revoked_token_key
from core.config import Settings
from core.exceptions import ConflictError, UnauthorizedError
from core.logging import get_logger
from models.user import User
from providers.interfaces.email_provider import EmailProvider
from providers.interfaces.hashing_provider import HashingProvider
from providers.interfaces.jwt_provider import JWTProvider
from repositories.user_repository import UserRepository

logger = get_logger(__name__)

# Redis key for storing a valid refresh token.
# Value: the user UUID. TTL: REFRESH_EXPIRE_DAYS * 86400 seconds.
_REFRESH_KEY = "hydra:auth:refresh:{jti}"


def _refresh_key(jti: str) -> str:
    return _REFRESH_KEY.format(jti=jti)


class AuthService:
    def __init__(
        self,
        *,
        user_repo: UserRepository,
        jwt_provider: JWTProvider,
        hasher: HashingProvider,
        email_provider: EmailProvider,
        redis: Redis,
        settings: Settings,
    ) -> None:
        self._user_repo = user_repo
        self._jwt = jwt_provider
        self._hasher = hasher
        self._email = email_provider
        self._redis = redis
        self._settings = settings
        self._access_ttl_seconds = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
        self._refresh_ttl_seconds = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400
        # Sentinel hash for timing-attack prevention — generated lazily on first
        # login so it uses the same Argon2 parameters as real password hashes.
        self._sentinel_hash: str | None = None

    async def _get_sentinel(self) -> str:
        """
        Return a valid Argon2id hash that always fails verification.

        Generated once per service instance (cached in self._sentinel_hash).
        The random input ensures it can never collide with a real user's hash.
        This is called when a login attempt uses an email that doesn't exist —
        we still run verify() so the response time is indistinguishable from
        a wrong-password attempt.
        """
        if self._sentinel_hash is None:
            self._sentinel_hash = await self._hasher.hash(secrets.token_hex(32))
        return self._sentinel_hash

    async def _issue_token_pair(
        self,
        user: User,
    ) -> tuple[str, str]:
        """
        Issue an (access_token, refresh_token) pair for a user.

        Stores the refresh token JTI in Redis so it can be revoked.
        The refresh token's JTI is the only thing Redis knows about — we
        don't store the full token, just evidence that this JTI is valid.
        """
        access_token = self._jwt.encode({"sub": str(user.id), "type": "access"})
        access_payload = self._jwt.decode(access_token)

        refresh_exp = datetime.now(timezone.utc) + timedelta(
            seconds=self._refresh_ttl_seconds
        )
        refresh_token = self._jwt.encode(
            {
                "sub": str(user.id),
                "type": "refresh",
                "exp": refresh_exp,  # overrides the provider's default access TTL
            }
        )
        refresh_payload = self._jwt.decode(refresh_token)

        # Store refresh JTI in Redis — presence means "this refresh token is valid"
        await self._redis.setex(
            _refresh_key(refresh_payload["jti"]),
            self._refresh_ttl_seconds,
            str(user.id),
        )

        logger.info(
            "auth.tokens_issued",
            user_id=str(user.id),
            access_jti=access_payload["jti"],
            refresh_jti=refresh_payload["jti"],
        )
        return access_token, refresh_token

    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str | None = None,
    ) -> tuple[str, str]:
        """
        Create a new user account and return a token pair.

        The user is immediately authenticated after registration — no need
        to make them log in again. Email verification is a separate step
        that doesn't block access (users get full access, verification just
        unlocks certain premium features).

        Raises:
            ConflictError: If the email is already registered.
        """
        email = email.strip().lower()
        if await self._user_repo.email_exists(email):
            raise ConflictError("An account with this email already exists")

        password_hash = await self._hasher.hash(password)
        user = await self._user_repo.create(
            email=email,
            password_hash=password_hash,
            full_name=full_name,
        )

        # Send verification email — fire and forget (don't await, don't block).
        # If email sending fails, the registration still succeeds.
        # The user can request a resend later.
        import asyncio

        asyncio.create_task(
            self._email.send(
                to=email,
                subject="Verify your Hydra email address",
                body_text=(
                    f"Hi {full_name or 'there'},\n\n"
                    "Welcome to Hydra! Please verify your email address by "
                    "clicking the link below (not implemented yet — coming in "
                    "a future milestone).\n\n"
                    "The Hydra Team"
                ),
            )
        )

        logger.info("auth.registered", user_id=str(user.id), email=email)
        return await self._issue_token_pair(user)

    async def login(
        self,
        *,
        email: str,
        password: str,
    ) -> tuple[str, str]:
        """
        Authenticate a user by email and password.

        Timing-attack resistant: always runs Argon2id verification even
        when the email doesn't exist. This ensures response time is the
        same whether the email is registered or not.

        Raises:
            UnauthorizedError: If credentials are invalid or account inactive.
        """
        user = await self._user_repo.get_by_email(email)

        # Always run verify, even on a dummy hash, to prevent email enumeration
        # via response-time measurement.
        hash_to_check = user.password_hash if user else await self._get_sentinel()
        valid = await self._hasher.verify(password, hash_to_check)

        if not user or not valid:
            raise UnauthorizedError("Invalid email or password")

        if not user.is_active:
            raise UnauthorizedError("Account is deactivated")

        # Upgrade hash parameters if the user's hash is outdated
        if valid and user and await self._hasher.needs_rehash(user.password_hash):
            user.password_hash = await self._hasher.hash(password)

        await self._user_repo.update_last_login(user)
        logger.info("auth.login", user_id=str(user.id))
        return await self._issue_token_pair(user)

    async def refresh(
        self,
        *,
        refresh_token: str,
    ) -> tuple[str, str]:
        """
        Issue a new token pair in exchange for a valid refresh token.

        Refresh token rotation: the old refresh token is deleted from Redis
        and a new one is issued. This limits the damage of a stolen refresh
        token — once used, it can't be used again.

        Raises:
            UnauthorizedError: If the refresh token is invalid, expired, or revoked.
        """
        try:
            payload = self._jwt.decode(refresh_token)
        except UnauthorizedError:
            raise UnauthorizedError("Invalid or expired refresh token")

        if payload.get("type") != "refresh":
            raise UnauthorizedError("Token is not a refresh token")

        jti = payload.get("jti")
        user_id_str = payload.get("sub")
        if not jti or not user_id_str:
            raise UnauthorizedError("Malformed refresh token")

        # Verify this JTI is still in Redis (not already used or revoked)
        stored = await self._redis.get(_refresh_key(jti))
        if stored is None:
            raise UnauthorizedError("Refresh token has been revoked or already used")

        # Rotation: delete old refresh token before issuing new pair
        await self._redis.delete(_refresh_key(jti))

        user = await self._user_repo.get_by_id(uuid.UUID(user_id_str))
        if not user or not user.is_active:
            raise UnauthorizedError("Account not found or deactivated")

        logger.info("auth.refreshed", user_id=user_id_str, old_jti=jti)
        return await self._issue_token_pair(user)

    async def logout(
        self,
        *,
        access_payload: dict[str, Any],
        refresh_token: str | None = None,
    ) -> None:
        """
        Invalidate the current session.

        1. Adds the access token's JTI to the Redis revocation set with TTL
           equal to the token's remaining lifetime. Access tokens are checked
           against this set on every authenticated request.
        2. If a refresh token is provided, deletes it from Redis.

        Args:
            access_payload: Decoded JWT payload from the Authorization header.
            refresh_token:  Optional raw refresh token string. If provided,
                            its JTI is deleted from the refresh token store.
        """
        access_jti = access_payload.get("jti")
        access_exp = access_payload.get("exp", 0)

        if access_jti:
            # TTL = seconds until the access token expires naturally.
            # After expiry, the token is invalid anyway — no need to keep the
            # revocation entry past that point.
            remaining = max(0, int(access_exp - datetime.now(timezone.utc).timestamp()))
            if remaining > 0:
                await self._redis.setex(
                    revoked_token_key(access_jti),
                    remaining,
                    "1",
                )

        if refresh_token:
            try:
                refresh_payload = self._jwt.decode(refresh_token)
                refresh_jti = refresh_payload.get("jti")
                if refresh_jti:
                    await self._redis.delete(_refresh_key(refresh_jti))
            except UnauthorizedError:
                # Expired refresh token on logout is fine — it's already invalid
                pass

        logger.info("auth.logout", access_jti=access_jti)

    async def get_user_from_token(self, payload: dict[str, Any]) -> User:
        """
        Load the user referenced by a decoded JWT payload.

        Called by get_current_user dependency after token validation.

        Raises:
            UnauthorizedError: If the user no longer exists or is inactive.
        """
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise UnauthorizedError("Token missing subject claim")

        user = await self._user_repo.get_by_id(uuid.UUID(user_id_str))
        if not user or not user.is_active:
            raise UnauthorizedError("Account not found or deactivated")

        return user
