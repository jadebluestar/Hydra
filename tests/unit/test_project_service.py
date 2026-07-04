"""Unit tests for ProjectService — no DB required."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import ConflictError, ForbiddenError
from services.project_service import ProjectService


def _make_membership(role: str = "member") -> MagicMock:
    m = MagicMock()
    m.role = role
    m.organization_id = uuid.uuid4()
    return m


def _make_project(org_id: uuid.UUID | None = None) -> MagicMock:
    p = MagicMock()
    p.id = uuid.uuid4()
    p.organization_id = org_id or uuid.uuid4()
    p.name = "My Project"
    p.slug = "my-project"
    return p


def _make_service(
    *,
    membership: MagicMock | None = None,
    project: MagicMock | None = None,
    slug_exists: bool = False,
) -> tuple[ProjectService, dict]:
    mock_membership = membership or _make_membership(role="owner")
    mock_project = project or _make_project(org_id=mock_membership.organization_id)

    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = mock_project
    project_repo.create.return_value = mock_project
    project_repo.save.return_value = mock_project
    project_repo.soft_delete.return_value = None
    project_repo.list_by_org.return_value = [mock_project]
    project_repo.slug_exists_in_org.return_value = slug_exists

    membership_repo = AsyncMock()
    membership_repo.get_by_org_and_user.return_value = mock_membership

    svc = ProjectService(
        project_repo=project_repo,
        membership_repo=membership_repo,
    )
    return svc, {
        "project": mock_project,
        "membership": mock_membership,
        "project_repo": project_repo,
        "membership_repo": membership_repo,
    }


class TestCreateProject:
    async def test_owner_can_create(self) -> None:
        svc, mocks = _make_service(membership=_make_membership(role="owner"))
        project = await svc.create(
            org_id=uuid.uuid4(),
            name="API Project",
            slug="api-project",
            description=None,
            requesting_user_id=uuid.uuid4(),
        )
        assert project is not None

    async def test_member_cannot_create(self) -> None:
        svc, _ = _make_service(membership=_make_membership(role="member"))
        with pytest.raises(ForbiddenError):
            await svc.create(
                org_id=uuid.uuid4(),
                name="My Project",
                slug=None,
                description=None,
                requesting_user_id=uuid.uuid4(),
            )

    async def test_viewer_cannot_create(self) -> None:
        svc, _ = _make_service(membership=_make_membership(role="viewer"))
        with pytest.raises(ForbiddenError):
            await svc.create(
                org_id=uuid.uuid4(),
                name="My Project",
                slug=None,
                description=None,
                requesting_user_id=uuid.uuid4(),
            )

    async def test_non_member_cannot_create(self) -> None:
        svc, mocks = _make_service()
        mocks["membership_repo"].get_by_org_and_user.return_value = None
        with pytest.raises(ForbiddenError):
            await svc.create(
                org_id=uuid.uuid4(),
                name="My Project",
                slug=None,
                description=None,
                requesting_user_id=uuid.uuid4(),
            )

    async def test_raises_conflict_if_slug_taken(self) -> None:
        svc, _ = _make_service(slug_exists=True)
        with pytest.raises(ConflictError, match="already exists"):
            await svc.create(
                org_id=uuid.uuid4(),
                name="My Project",
                slug="taken-slug",
                description=None,
                requesting_user_id=uuid.uuid4(),
            )

    async def test_auto_generates_slug_from_name(self) -> None:
        svc, mocks = _make_service()
        await svc.create(
            org_id=uuid.uuid4(),
            name="My Awesome Project",
            slug=None,
            description=None,
            requesting_user_id=uuid.uuid4(),
        )
        call_kwargs = mocks["project_repo"].create.call_args.kwargs
        assert call_kwargs["slug"] == "my-awesome-project"


class TestUpdateProject:
    async def test_admin_can_update(self) -> None:
        svc, mocks = _make_service(membership=_make_membership(role="admin"))
        await svc.update(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
            name="New Name",
        )
        mocks["project_repo"].save.assert_awaited()

    async def test_viewer_cannot_update(self) -> None:
        svc, _ = _make_service(membership=_make_membership(role="viewer"))
        with pytest.raises(ForbiddenError):
            await svc.update(
                project_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
                name="New Name",
            )

    async def test_non_member_cannot_update(self) -> None:
        svc, mocks = _make_service()
        mocks["membership_repo"].get_by_org_and_user.return_value = None
        with pytest.raises(ForbiddenError):
            await svc.update(
                project_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
                name="New Name",
            )


class TestDeleteProject:
    async def test_owner_can_delete(self) -> None:
        svc, mocks = _make_service(membership=_make_membership(role="owner"))
        await svc.delete(project_id=uuid.uuid4(), requesting_user_id=uuid.uuid4())
        mocks["project_repo"].soft_delete.assert_awaited_once()

    async def test_member_cannot_delete(self) -> None:
        svc, _ = _make_service(membership=_make_membership(role="member"))
        with pytest.raises(ForbiddenError):
            await svc.delete(project_id=uuid.uuid4(), requesting_user_id=uuid.uuid4())
