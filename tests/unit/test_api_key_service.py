"""Unit tests for APIKeyService and the api_key utility functions."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import ForbiddenError, NotFoundError
from utils.api_key import extract_prefix, generate_api_key, verify_key


# ── Key generation utilities ──────────────────────────────────────────────────


class TestGenerateAPIKey:
    def test_returns_three_values(self) -> None:
        full_key, prefix, key_hash = generate_api_key()
        assert full_key and prefix and key_hash

    def test_key_starts_with_hk_live(self) -> None:
        full_key, _, _ = generate_api_key(env="live")
        assert full_key.startswith("hk_live_")

    def test_key_starts_with_hk_test_for_test_env(self) -> None:
        full_key, _, _ = generate_api_key(env="test")
        assert full_key.startswith("hk_test_")

    def test_prefix_is_first_16_chars(self) -> None:
        full_key, prefix, _ = generate_api_key()
        assert prefix == full_key[:16]

    def test_prefix_length_is_16(self) -> None:
        _, prefix, _ = generate_api_key()
        assert len(prefix) == 16

    def test_hash_is_64_hex_chars(self) -> None:
        _, _, key_hash = generate_api_key()
        assert len(key_hash) == 64
        assert all(c in "0123456789abcdef" for c in key_hash)

    def test_each_call_produces_unique_key(self) -> None:
        keys = [generate_api_key()[0] for _ in range(10)]
        assert len(set(keys)) == 10

    def test_full_key_total_length(self) -> None:
        # "hk_live_" + 32 hex chars = 40 chars
        full_key, _, _ = generate_api_key(env="live")
        assert len(full_key) == 40


class TestVerifyKey:
    def test_correct_key_returns_true(self) -> None:
        full_key, _, key_hash = generate_api_key()
        assert verify_key(full_key, key_hash) is True

    def test_wrong_key_returns_false(self) -> None:
        full_key, _, key_hash = generate_api_key()
        tampered = full_key[:-4] + "XXXX"
        assert verify_key(tampered, key_hash) is False

    def test_different_key_returns_false(self) -> None:
        full_key, _, key_hash = generate_api_key()
        other_key, _, _ = generate_api_key()
        assert verify_key(other_key, key_hash) is False

    def test_empty_string_returns_false(self) -> None:
        _, _, key_hash = generate_api_key()
        assert verify_key("", key_hash) is False


class TestExtractPrefix:
    def test_returns_first_16_chars(self) -> None:
        full_key, expected_prefix, _ = generate_api_key()
        assert extract_prefix(full_key) == expected_prefix

    def test_prefix_matches_stored_prefix(self) -> None:
        full_key, stored_prefix, _ = generate_api_key()
        assert extract_prefix(full_key) == stored_prefix


# ── APIKeyService ─────────────────────────────────────────────────────────────


def _make_membership(role: str = "owner") -> MagicMock:
    m = MagicMock()
    m.role = role
    m.organization_id = uuid.uuid4()
    return m


def _make_api_key(*, is_active: bool = True, is_revoked: bool = False) -> MagicMock:
    k = MagicMock()
    k.id = uuid.uuid4()
    k.project_id = uuid.uuid4()
    k.is_active = is_active
    k.is_revoked = is_revoked
    k.key_hash = "abc123"
    return k


def _make_project(org_id: uuid.UUID | None = None) -> MagicMock:
    p = MagicMock()
    p.id = uuid.uuid4()
    p.organization_id = org_id or uuid.uuid4()
    return p


def _make_svc(
    *,
    membership: MagicMock | None = None,
    api_key: MagicMock | None = None,
) -> tuple:
    from services.api_key_service import APIKeyService

    mock_project = _make_project()
    mock_key = api_key or _make_api_key()
    mock_membership = membership or _make_membership(role="owner")

    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = mock_project

    membership_repo = AsyncMock()
    membership_repo.get_by_org_and_user.return_value = mock_membership

    key_repo = AsyncMock()
    key_repo.create.return_value = mock_key
    key_repo.list_by_project.return_value = [mock_key]
    key_repo.get_by_id.return_value = mock_key
    key_repo.revoke.return_value = None
    key_repo.get_candidates_by_prefix.return_value = [mock_key]

    svc = APIKeyService(
        api_key_repo=key_repo,
        project_repo=project_repo,
        membership_repo=membership_repo,
    )
    return svc, {
        "key": mock_key,
        "project": mock_project,
        "key_repo": key_repo,
        "membership_repo": membership_repo,
    }


class TestAPIKeyServiceCreate:
    async def test_owner_can_create_key(self) -> None:
        svc, _ = _make_svc(membership=_make_membership(role="owner"))
        api_key, full_key = await svc.create(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
            name="Test Key",
            scopes=["gateway:read"],
        )
        assert api_key is not None
        assert full_key.startswith("hk_live_")

    async def test_member_can_create_key(self) -> None:
        svc, _ = _make_svc(membership=_make_membership(role="member"))
        api_key, full_key = await svc.create(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
            name="Test Key",
            scopes=[],
        )
        assert full_key is not None

    async def test_viewer_cannot_create_key(self) -> None:
        svc, _ = _make_svc(membership=_make_membership(role="viewer"))
        with pytest.raises(ForbiddenError):
            await svc.create(
                project_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
                name="Test Key",
                scopes=[],
            )

    async def test_returned_full_key_is_different_each_time(self) -> None:
        svc, _ = _make_svc()
        _, key1 = await svc.create(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
            name="Key 1",
            scopes=[],
        )
        _, key2 = await svc.create(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
            name="Key 2",
            scopes=[],
        )
        assert key1 != key2

    async def test_stores_hash_not_plaintext(self) -> None:
        svc, mocks = _make_svc()
        _, full_key = await svc.create(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
            name="Test Key",
            scopes=[],
        )
        stored_hash = mocks["key_repo"].create.call_args.kwargs["key_hash"]
        # The stored hash is NOT the plaintext key
        assert stored_hash != full_key
        # And it's a SHA-256 hex string (64 chars)
        assert len(stored_hash) == 64


class TestAPIKeyServiceRevoke:
    async def test_owner_can_revoke(self) -> None:
        svc, mocks = _make_svc(membership=_make_membership(role="owner"))
        await svc.revoke(key_id=uuid.uuid4(), requesting_user_id=uuid.uuid4())
        mocks["key_repo"].revoke.assert_awaited_once()

    async def test_revoke_nonexistent_key_raises_not_found(self) -> None:
        svc, mocks = _make_svc()
        mocks["key_repo"].get_by_id.return_value = None
        with pytest.raises(NotFoundError):
            await svc.revoke(key_id=uuid.uuid4(), requesting_user_id=uuid.uuid4())

    async def test_revoke_already_revoked_is_noop(self) -> None:
        already_revoked = _make_api_key(is_revoked=True)
        svc, mocks = _make_svc(api_key=already_revoked)
        await svc.revoke(key_id=uuid.uuid4(), requesting_user_id=uuid.uuid4())
        mocks["key_repo"].revoke.assert_not_awaited()

    async def test_viewer_cannot_revoke(self) -> None:
        svc, _ = _make_svc(membership=_make_membership(role="viewer"))
        with pytest.raises(ForbiddenError):
            await svc.revoke(key_id=uuid.uuid4(), requesting_user_id=uuid.uuid4())


class TestAPIKeyServiceVerify:
    async def test_verify_returns_key_for_valid_raw_key(self) -> None:
        full_key, prefix, key_hash = generate_api_key()

        mock_key = _make_api_key(is_active=True)
        mock_key.key_hash = key_hash
        mock_key.key_prefix = prefix

        svc, mocks = _make_svc(api_key=mock_key)
        mocks["key_repo"].get_candidates_by_prefix.return_value = [mock_key]

        result = await svc.verify(full_key)
        assert result is mock_key

    async def test_verify_returns_none_for_wrong_key(self) -> None:
        _, _, key_hash = generate_api_key()
        other_key, _, _ = generate_api_key()

        mock_key = _make_api_key(is_active=True)
        mock_key.key_hash = key_hash

        svc, mocks = _make_svc(api_key=mock_key)
        mocks["key_repo"].get_candidates_by_prefix.return_value = [mock_key]

        result = await svc.verify(other_key)
        assert result is None

    async def test_verify_returns_none_for_inactive_key(self) -> None:
        full_key, _, key_hash = generate_api_key()

        mock_key = _make_api_key(is_active=False)
        mock_key.key_hash = key_hash

        svc, mocks = _make_svc(api_key=mock_key)
        mocks["key_repo"].get_candidates_by_prefix.return_value = [mock_key]

        result = await svc.verify(full_key)
        assert result is None

    async def test_verify_returns_none_when_no_candidates(self) -> None:
        full_key, _, _ = generate_api_key()
        svc, mocks = _make_svc()
        mocks["key_repo"].get_candidates_by_prefix.return_value = []
        result = await svc.verify(full_key)
        assert result is None
