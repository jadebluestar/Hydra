"""
Unit tests for AuthService.

All dependencies are mocked — no database, no Redis, no real hashing.
The Argon2 hasher mock returns instantly, so tests run in milliseconds.

Pattern: each test builds a fake AuthService with the minimum mocks needed,
calls one method, and asserts on the observable outcome (return value or
side effects on the mocks).

AsyncMock is Python's standard tool for mocking async functions. It returns
an awaitable that resolves to a configured return_value.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import ConflictError, UnauthorizedError
from services.auth_service import AuthService

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_user(
    *,
    user_id: uuid.UUID | None = None,
    email: str = "alice@example.com",
    is_active: bool = True,
    password_hash: str = "$argon2id$fake",
) -> MagicMock:
    """Build a mock User object with the fields AuthService cares about."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = email
    user.is_active = is_active
    user.password_hash = password_hash
    return user


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 15
    s.JWT_REFRESH_TOKEN_EXPIRE_DAYS = 7
    return s


def _make_service(
    *,
    user: MagicMock | None = None,
    email_exists: bool = False,
    password_valid: bool = True,
    needs_rehash: bool = False,
) -> tuple[AuthService, dict[str, Any]]:
    """
    Build an AuthService with fully mocked dependencies.

    Returns (service, mocks) so tests can inspect mock call counts/args.
    """
    mock_user = user or _make_user()

    user_repo = AsyncMock()
    user_repo.email_exists.return_value = email_exists
    user_repo.get_by_email.return_value = mock_user if not email_exists else None
    user_repo.create.return_value = mock_user
    user_repo.get_by_id.return_value = mock_user
    user_repo.update_last_login.return_value = None

    jwt_provider = MagicMock()

    # encode() returns a fake token string; decode() returns a plausible payload
    def _fake_encode(payload: dict) -> str:
        return f"fake_token_{payload.get('type', 'access')}"

    def _fake_decode(token: str) -> dict:
        if "refresh" in token:
            return {
                "sub": str(mock_user.id),
                "type": "refresh",
                "jti": str(uuid.uuid4()),
                "exp": 9999999999,
            }
        return {
            "sub": str(mock_user.id),
            "type": "access",
            "jti": str(uuid.uuid4()),
            "exp": 9999999999,
        }

    jwt_provider.encode.side_effect = _fake_encode
    jwt_provider.decode.side_effect = _fake_decode

    hasher = AsyncMock()
    hasher.hash.return_value = "$argon2id$fake_hash"
    hasher.verify.return_value = password_valid
    hasher.needs_rehash.return_value = needs_rehash

    email_provider = AsyncMock()
    email_provider.send.return_value = None

    redis = AsyncMock()
    redis.setex.return_value = True
    redis.get.return_value = str(mock_user.id)  # refresh token exists in Redis
    redis.delete.return_value = 1

    settings = _make_settings()

    service = AuthService(
        user_repo=user_repo,
        jwt_provider=jwt_provider,
        hasher=hasher,
        email_provider=email_provider,
        redis=redis,
        settings=settings,
    )

    mocks = {
        "user": mock_user,
        "user_repo": user_repo,
        "jwt_provider": jwt_provider,
        "hasher": hasher,
        "email_provider": email_provider,
        "redis": redis,
    }
    return service, mocks


# ── Register ──────────────────────────────────────────────────────────────────


class TestRegister:
    async def test_returns_token_pair(self) -> None:
        svc, _ = _make_service()
        access, refresh = await svc.register(email="alice@example.com", password="secure-pass-123")
        assert isinstance(access, str) and len(access) > 0
        assert isinstance(refresh, str) and len(refresh) > 0

    async def test_hashes_password_before_storing(self) -> None:
        svc, mocks = _make_service()
        await svc.register(email="alice@example.com", password="secure-pass-123")
        mocks["hasher"].hash.assert_awaited_once_with("secure-pass-123")

    async def test_creates_user_with_normalized_email(self) -> None:
        svc, mocks = _make_service()
        await svc.register(email="Alice@EXAMPLE.COM", password="secure-pass-123")
        call_kwargs = mocks["user_repo"].create.call_args.kwargs
        # UserRepository.create normalizes email
        assert "alice@example.com" in call_kwargs.get("email", "")

    async def test_raises_conflict_if_email_taken(self) -> None:
        svc, _ = _make_service(email_exists=True)
        with pytest.raises(ConflictError, match="already exists"):
            await svc.register(email="alice@example.com", password="secure-pass-123")

    async def test_does_not_hash_password_if_email_taken(self) -> None:
        svc, mocks = _make_service(email_exists=True)
        with pytest.raises(ConflictError):
            await svc.register(email="alice@example.com", password="secure-pass-123")
        mocks["hasher"].hash.assert_not_awaited()

    async def test_stores_refresh_token_in_redis(self) -> None:
        svc, mocks = _make_service()
        await svc.register(email="alice@example.com", password="secure-pass-123")
        # setex called once for the refresh token
        mocks["redis"].setex.assert_awaited()

    async def test_returns_two_different_tokens(self) -> None:
        svc, _ = _make_service()
        access, refresh = await svc.register(email="alice@example.com", password="secure-pass-123")
        assert access != refresh


# ── Login ─────────────────────────────────────────────────────────────────────


class TestLogin:
    async def test_returns_token_pair_on_success(self) -> None:
        svc, _ = _make_service(password_valid=True)
        access, refresh = await svc.login(email="alice@example.com", password="correct")
        assert isinstance(access, str)
        assert isinstance(refresh, str)

    async def test_raises_unauthorized_on_wrong_password(self) -> None:
        svc, _ = _make_service(password_valid=False)
        with pytest.raises(UnauthorizedError, match="Invalid"):
            await svc.login(email="alice@example.com", password="wrong")

    async def test_raises_unauthorized_when_user_not_found(self) -> None:
        svc, mocks = _make_service(password_valid=False)
        mocks["user_repo"].get_by_email.return_value = None
        with pytest.raises(UnauthorizedError):
            await svc.login(email="ghost@example.com", password="anything")

    async def test_always_runs_verify_even_when_user_not_found(self) -> None:
        """Timing-attack prevention: verify() must run even on unknown email."""
        svc, mocks = _make_service(password_valid=False)
        mocks["user_repo"].get_by_email.return_value = None
        with pytest.raises(UnauthorizedError):
            await svc.login(email="ghost@example.com", password="anything")
        # hasher.verify MUST have been called (not short-circuited)
        mocks["hasher"].verify.assert_awaited_once()

    async def test_raises_unauthorized_when_user_inactive(self) -> None:
        inactive_user = _make_user(is_active=False)
        svc, _ = _make_service(user=inactive_user, password_valid=True)
        with pytest.raises(UnauthorizedError, match="deactivated"):
            await svc.login(email="alice@example.com", password="correct")

    async def test_updates_last_login_on_success(self) -> None:
        svc, mocks = _make_service(password_valid=True)
        await svc.login(email="alice@example.com", password="correct")
        mocks["user_repo"].update_last_login.assert_awaited_once()

    async def test_rehashes_password_if_needed(self) -> None:
        svc, mocks = _make_service(password_valid=True, needs_rehash=True)
        await svc.login(email="alice@example.com", password="correct")
        mocks["hasher"].hash.assert_awaited_once_with("correct")


# ── Refresh ───────────────────────────────────────────────────────────────────


class TestRefresh:
    async def test_returns_new_token_pair(self) -> None:
        svc, _ = _make_service()
        access, refresh = await svc.refresh(refresh_token="fake_token_refresh")
        assert isinstance(access, str)
        assert isinstance(refresh, str)

    async def test_raises_if_token_type_is_not_refresh(self) -> None:
        svc, mocks = _make_service()
        # Make decode return type="access"
        mocks["jwt_provider"].decode.side_effect = lambda t: {
            "sub": "some-id",
            "type": "access",  # wrong type
            "jti": str(uuid.uuid4()),
            "exp": 9999999999,
        }
        with pytest.raises(UnauthorizedError, match="not a refresh token"):
            await svc.refresh(refresh_token="some_access_token")

    async def test_raises_if_refresh_token_not_in_redis(self) -> None:
        svc, mocks = _make_service()
        mocks["redis"].get.return_value = None  # not in Redis = revoked
        with pytest.raises(UnauthorizedError, match="revoked"):
            await svc.refresh(refresh_token="fake_token_refresh")

    async def test_deletes_old_refresh_token_from_redis(self) -> None:
        """Refresh token rotation: old token must be deleted."""
        svc, mocks = _make_service()
        await svc.refresh(refresh_token="fake_token_refresh")
        mocks["redis"].delete.assert_awaited()


# ── Logout ────────────────────────────────────────────────────────────────────


class TestLogout:
    async def test_adds_access_jti_to_revocation_set(self) -> None:
        svc, mocks = _make_service()
        future_exp = int(datetime.now(UTC).timestamp()) + 900
        await svc.logout(
            access_payload={"jti": "some-jti", "exp": future_exp},
        )
        mocks["redis"].setex.assert_awaited()

    async def test_deletes_refresh_token_from_redis_if_provided(self) -> None:
        svc, mocks = _make_service()
        future_exp = int(datetime.now(UTC).timestamp()) + 900
        await svc.logout(
            access_payload={"jti": "some-jti", "exp": future_exp},
            refresh_token="fake_token_refresh",
        )
        mocks["redis"].delete.assert_awaited()

    async def test_does_not_add_expired_token_to_revocation_set(self) -> None:
        """No point revoking an already-expired token."""
        svc, mocks = _make_service()
        past_exp = int(datetime.now(UTC).timestamp()) - 1
        await svc.logout(
            access_payload={"jti": "some-jti", "exp": past_exp},
        )
        # setex should NOT have been called (remaining TTL = 0)
        mocks["redis"].setex.assert_not_awaited()
