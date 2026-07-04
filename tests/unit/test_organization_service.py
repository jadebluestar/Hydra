"""
Unit tests for OrganizationService.

All repositories are mocked — no DB required. Tests verify:
  - Correct permission checks are applied
  - Business invariants (last-owner protection) are enforced
  - Repository methods are called with the right arguments
  - Domain exceptions are raised for error cases
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import ConflictError, ForbiddenError, NotFoundError
from services.organization_service import OrganizationService

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_membership(
    *,
    org_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    role: str = "member",
) -> MagicMock:
    m = MagicMock()
    m.organization_id = org_id or uuid.uuid4()
    m.user_id = user_id or uuid.uuid4()
    m.role = role
    m.joined_at = None
    m.created_at = MagicMock()
    m.user = MagicMock()
    m.user.email = "member@example.com"
    m.user.full_name = "Test User"
    return m


def _make_org(slug: str = "acme") -> MagicMock:
    org = MagicMock()
    org.id = uuid.uuid4()
    org.name = "Acme Corp"
    org.slug = slug
    org.plan = "free"
    return org


def _make_service(
    *,
    membership: MagicMock | None = None,
    org: MagicMock | None = None,
    slug_exists: bool = False,
    email_exists: bool = True,
    members: list[MagicMock] | None = None,
) -> tuple[OrganizationService, dict[str, Any]]:
    mock_org = org or _make_org()
    mock_membership = membership or _make_membership(org_id=mock_org.id, role="owner")

    org_repo = AsyncMock()
    org_repo.slug_exists.return_value = slug_exists
    org_repo.create.return_value = mock_org
    org_repo.get_by_id.return_value = mock_org
    org_repo.get_by_slug.return_value = mock_org
    org_repo.list_for_user.return_value = [mock_org]
    org_repo.save.return_value = mock_org
    org_repo.soft_delete.return_value = None

    membership_repo = AsyncMock()
    membership_repo.get_by_org_and_user.return_value = mock_membership
    membership_repo.list_by_org.return_value = members or [mock_membership]
    membership_repo.create.return_value = mock_membership
    membership_repo.save.return_value = mock_membership
    membership_repo.delete.return_value = None

    user_repo = AsyncMock()
    mock_invited_user = MagicMock()
    mock_invited_user.id = uuid.uuid4()
    mock_invited_user.email = "invited@example.com"
    user_repo.get_by_email.return_value = mock_invited_user if email_exists else None

    svc = OrganizationService(
        org_repo=org_repo,
        membership_repo=membership_repo,
        user_repo=user_repo,
    )

    mocks = {
        "org": mock_org,
        "membership": mock_membership,
        "org_repo": org_repo,
        "membership_repo": membership_repo,
        "user_repo": user_repo,
    }
    return svc, mocks


# ── Create ────────────────────────────────────────────────────────────────────


class TestCreate:
    async def test_returns_org(self) -> None:
        svc, _ = _make_service()
        owner_id = uuid.uuid4()
        org = await svc.create(name="Acme", slug="acme", owner_user_id=owner_id)
        assert org is not None

    async def test_creates_owner_membership(self) -> None:
        svc, mocks = _make_service()
        owner_id = uuid.uuid4()
        await svc.create(name="Acme", slug="acme", owner_user_id=owner_id)
        mocks["membership_repo"].create.assert_awaited_once()
        call_kwargs = mocks["membership_repo"].create.call_args.kwargs
        assert call_kwargs["role"] == "owner"
        assert call_kwargs["user_id"] == owner_id

    async def test_raises_conflict_if_slug_taken(self) -> None:
        svc, _ = _make_service(slug_exists=True)
        with pytest.raises(ConflictError, match="already taken"):
            await svc.create(name="Acme", slug="acme", owner_user_id=uuid.uuid4())

    async def test_auto_generates_slug_from_name(self) -> None:
        svc, mocks = _make_service()
        await svc.create(name="My Awesome Company", slug=None, owner_user_id=uuid.uuid4())
        call_kwargs = mocks["org_repo"].create.call_args.kwargs
        assert call_kwargs["slug"] == "my-awesome-company"

    async def test_does_not_create_org_if_slug_taken(self) -> None:
        svc, mocks = _make_service(slug_exists=True)
        with pytest.raises(ConflictError):
            await svc.create(name="Acme", slug="acme", owner_user_id=uuid.uuid4())
        mocks["org_repo"].create.assert_not_awaited()


# ── Get by slug ───────────────────────────────────────────────────────────────


class TestGetBySlug:
    async def test_returns_org_for_member(self) -> None:
        svc, _ = _make_service()
        org = await svc.get_by_slug(slug="acme", requesting_user_id=uuid.uuid4())
        assert org is not None

    async def test_raises_forbidden_if_not_member(self) -> None:
        svc, mocks = _make_service()
        mocks["membership_repo"].get_by_org_and_user.return_value = None
        with pytest.raises(ForbiddenError):
            await svc.get_by_slug(slug="acme", requesting_user_id=uuid.uuid4())

    async def test_raises_forbidden_if_org_not_found(self) -> None:
        svc, mocks = _make_service()
        mocks["org_repo"].get_by_slug.return_value = None
        with pytest.raises(ForbiddenError):
            await svc.get_by_slug(slug="no-such-org", requesting_user_id=uuid.uuid4())


# ── Update ────────────────────────────────────────────────────────────────────


class TestUpdate:
    async def test_owner_can_update_name(self) -> None:
        svc, mocks = _make_service()
        owner_membership = _make_membership(role="owner")
        mocks["membership_repo"].get_by_org_and_user.return_value = owner_membership
        await svc.update(
            org_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
            name="New Name",
        )
        mocks["org_repo"].save.assert_awaited()

    async def test_viewer_cannot_update(self) -> None:
        svc, mocks = _make_service()
        viewer_membership = _make_membership(role="viewer")
        mocks["membership_repo"].get_by_org_and_user.return_value = viewer_membership
        with pytest.raises(ForbiddenError):
            await svc.update(
                org_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
                name="New Name",
            )

    async def test_non_member_cannot_update(self) -> None:
        svc, mocks = _make_service()
        mocks["membership_repo"].get_by_org_and_user.return_value = None
        with pytest.raises(ForbiddenError):
            await svc.update(
                org_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
                name="New Name",
            )


# ── Delete ────────────────────────────────────────────────────────────────────


class TestDelete:
    async def test_owner_can_delete(self) -> None:
        owner_membership = _make_membership(role="owner")
        svc, mocks = _make_service(membership=owner_membership)
        await svc.delete(org_id=uuid.uuid4(), requesting_user_id=uuid.uuid4())
        mocks["org_repo"].soft_delete.assert_awaited_once()

    async def test_admin_cannot_delete(self) -> None:
        admin_membership = _make_membership(role="admin")
        svc, _ = _make_service(membership=admin_membership)
        with pytest.raises(ForbiddenError):
            await svc.delete(org_id=uuid.uuid4(), requesting_user_id=uuid.uuid4())


# ── Invite member ─────────────────────────────────────────────────────────────


class TestInviteMember:
    async def test_owner_can_invite_member(self) -> None:
        owner_membership = _make_membership(role="owner")
        svc, mocks = _make_service(membership=owner_membership)
        # No existing membership for the invited user
        mocks["membership_repo"].get_by_org_and_user.side_effect = [
            owner_membership,  # first call: requester's membership
            owner_membership,  # second call (for role rank check): same
            None,  # third call: invited user has no membership
        ]
        await svc.invite_member(
            org_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
            email="new@example.com",
            role="member",
        )
        mocks["membership_repo"].create.assert_awaited_once()

    async def test_raises_not_found_if_email_has_no_account(self) -> None:
        owner_membership = _make_membership(role="owner")
        svc, mocks = _make_service(membership=owner_membership, email_exists=False)
        with pytest.raises(NotFoundError, match="No account"):
            await svc.invite_member(
                org_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
                email="ghost@example.com",
                role="member",
            )

    async def test_raises_conflict_if_already_member(self) -> None:
        owner_membership = _make_membership(role="owner")
        svc, mocks = _make_service(membership=owner_membership)
        existing_membership = _make_membership(role="member")
        mocks["membership_repo"].get_by_org_and_user.side_effect = [
            owner_membership,  # requester's membership
            owner_membership,  # role rank check
            existing_membership,  # invited user already has membership
        ]
        with pytest.raises(ConflictError, match="already a member"):
            await svc.invite_member(
                org_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
                email="existing@example.com",
                role="member",
            )

    async def test_viewer_cannot_invite(self) -> None:
        viewer_membership = _make_membership(role="viewer")
        svc, _ = _make_service(membership=viewer_membership)
        with pytest.raises(ForbiddenError):
            await svc.invite_member(
                org_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
                email="new@example.com",
                role="member",
            )


# ── Remove member ─────────────────────────────────────────────────────────────


class TestRemoveMember:
    async def test_admin_can_remove_member(self) -> None:
        admin_membership = _make_membership(role="admin")
        target_membership = _make_membership(role="member")
        svc, mocks = _make_service(membership=admin_membership)
        mocks["membership_repo"].get_by_org_and_user.side_effect = [
            admin_membership,
            target_membership,
        ]
        await svc.remove_member(
            org_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
            target_user_id=uuid.uuid4(),
        )
        mocks["membership_repo"].delete.assert_awaited_once()

    async def test_cannot_remove_last_owner(self) -> None:
        owner_membership = _make_membership(role="owner")
        svc, mocks = _make_service(membership=owner_membership)
        # Target is also owner, and they're the only one
        target_owner = _make_membership(role="owner")
        mocks["membership_repo"].get_by_org_and_user.side_effect = [
            owner_membership,
            target_owner,
        ]
        mocks["membership_repo"].list_by_org.return_value = [owner_membership]
        with pytest.raises(ForbiddenError, match="last owner"):
            await svc.remove_member(
                org_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
                target_user_id=uuid.uuid4(),
            )

    async def test_member_can_remove_themselves(self) -> None:
        """Self-removal doesn't require REMOVE_MEMBER permission."""
        member_membership = _make_membership(role="member")
        user_id = uuid.uuid4()
        member_membership.user_id = user_id
        svc, mocks = _make_service(membership=member_membership)
        mocks["membership_repo"].get_by_org_and_user.return_value = member_membership
        await svc.remove_member(
            org_id=uuid.uuid4(),
            requesting_user_id=user_id,
            target_user_id=user_id,  # same user — self-removal
        )
        mocks["membership_repo"].delete.assert_awaited_once()


# ── Slugify utility ───────────────────────────────────────────────────────────


class TestSlugify:
    def test_basic_name(self) -> None:
        from utils.slugify import slugify

        assert slugify("Acme Corp") == "acme-corp"

    def test_special_chars_removed(self) -> None:
        from utils.slugify import slugify

        assert slugify("Hello, World!") == "hello-world"

    def test_leading_trailing_hyphens_stripped(self) -> None:
        from utils.slugify import slugify

        result = slugify("  Spaced  ")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_max_length_63(self) -> None:
        from utils.slugify import slugify

        long_name = "a" * 100
        assert len(slugify(long_name)) <= 63

    def test_valid_slug_accepted(self) -> None:
        from utils.slugify import is_valid_slug

        assert is_valid_slug("acme-corp") is True
        assert is_valid_slug("my-org-123") is True

    def test_invalid_slug_rejected(self) -> None:
        from utils.slugify import is_valid_slug

        assert is_valid_slug("AB") is False  # too short
        assert is_valid_slug("-starts-with-hyphen") is False
        assert is_valid_slug("has spaces") is False
        assert is_valid_slug("HAS_UPPERCASE") is False
