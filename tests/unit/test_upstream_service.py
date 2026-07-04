"""Unit tests for UpstreamService — no DB required."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import ForbiddenError, NotFoundError
from services.upstream_service import UpstreamService


def _make_membership(role: str = "member") -> MagicMock:
    m = MagicMock()
    m.role = role
    m.organization_id = uuid.uuid4()
    return m


def _make_upstream(project_id: uuid.UUID | None = None) -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.project_id = project_id or uuid.uuid4()
    u.name = "user-service"
    u.base_url = "http://user-svc:8080"
    u.timeout_seconds = 30
    u.retries = 3
    return u


def _make_project(org_id: uuid.UUID | None = None) -> MagicMock:
    p = MagicMock()
    p.id = uuid.uuid4()
    p.organization_id = org_id or uuid.uuid4()
    return p


def _make_svc(
    *,
    membership: MagicMock | None = None,
    upstream: MagicMock | None = None,
) -> tuple[UpstreamService, dict]:
    mock_membership = membership or _make_membership(role="member")
    mock_project = _make_project()
    mock_upstream = upstream or _make_upstream(project_id=mock_project.id)

    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = mock_project

    membership_repo = AsyncMock()
    membership_repo.get_by_org_and_user.return_value = mock_membership

    upstream_repo = AsyncMock()
    upstream_repo.get_by_id.return_value = mock_upstream
    upstream_repo.create.return_value = mock_upstream
    upstream_repo.save.return_value = mock_upstream
    upstream_repo.list_by_project.return_value = [mock_upstream]
    upstream_repo.soft_delete.return_value = None

    svc = UpstreamService(
        upstream_repo=upstream_repo,
        project_repo=project_repo,
        membership_repo=membership_repo,
    )
    return svc, {
        "upstream": mock_upstream,
        "project": mock_project,
        "upstream_repo": upstream_repo,
        "membership_repo": membership_repo,
    }


# ── create ────────────────────────────────────────────────────────────────────


class TestUpstreamServiceCreate:
    async def test_member_can_create(self) -> None:
        svc, _ = _make_svc(membership=_make_membership(role="member"))
        upstream = await svc.create(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
            name="user-service",
            base_url="http://user-svc:8080",
        )
        assert upstream is not None

    async def test_admin_can_create(self) -> None:
        svc, _ = _make_svc(membership=_make_membership(role="admin"))
        upstream = await svc.create(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
            name="user-service",
            base_url="http://user-svc:8080",
        )
        assert upstream is not None

    async def test_viewer_cannot_create(self) -> None:
        svc, _ = _make_svc(membership=_make_membership(role="viewer"))
        with pytest.raises(ForbiddenError):
            await svc.create(
                project_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
                name="user-service",
                base_url="http://user-svc:8080",
            )

    async def test_non_member_cannot_create(self) -> None:
        svc, mocks = _make_svc()
        mocks["membership_repo"].get_by_org_and_user.return_value = None
        with pytest.raises(ForbiddenError):
            await svc.create(
                project_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
                name="user-service",
                base_url="http://user-svc:8080",
            )

    async def test_create_passes_correct_args_to_repo(self) -> None:
        svc, mocks = _make_svc()
        project_id = uuid.uuid4()
        await svc.create(
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
            name="billing-service",
            base_url="https://billing.internal",
            timeout_seconds=60,
            retries=1,
        )
        mocks["upstream_repo"].create.assert_awaited_once_with(
            project_id=project_id,
            name="billing-service",
            base_url="https://billing.internal",
            timeout_seconds=60,
            retries=1,
        )

    async def test_unknown_project_raises_forbidden(self) -> None:
        svc, mocks = _make_svc()
        mocks["upstream_repo"].get_by_id  # not called here; project check fails
        from unittest.mock import AsyncMock
        svc._projects.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(ForbiddenError):
            await svc.create(
                project_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
                name="x",
                base_url="http://x",
            )


# ── list ─────────────────────────────────────────────────────────────────────


class TestUpstreamServiceList:
    async def test_viewer_can_list(self) -> None:
        svc, mocks = _make_svc(membership=_make_membership(role="viewer"))
        results = await svc.list(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
        )
        assert len(results) == 1

    async def test_non_member_cannot_list(self) -> None:
        svc, mocks = _make_svc()
        mocks["membership_repo"].get_by_org_and_user.return_value = None
        with pytest.raises(ForbiddenError):
            await svc.list(project_id=uuid.uuid4(), requesting_user_id=uuid.uuid4())


# ── get ──────────────────────────────────────────────────────────────────────


class TestUpstreamServiceGet:
    async def test_member_can_get(self) -> None:
        project_id = uuid.uuid4()
        mock_upstream = _make_upstream(project_id=project_id)
        svc, mocks = _make_svc(
            membership=_make_membership(role="member"),
            upstream=mock_upstream,
        )
        # Ensure project_repo returns a project with matching id
        mocks["upstream_repo"].get_by_id.return_value = mock_upstream

        result = await svc.get(
            upstream_id=mock_upstream.id,
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
        )
        assert result is mock_upstream

    async def test_upstream_from_different_project_raises_not_found(self) -> None:
        other_project_id = uuid.uuid4()
        mock_upstream = _make_upstream(project_id=other_project_id)
        svc, mocks = _make_svc(upstream=mock_upstream)

        with pytest.raises(NotFoundError):
            await svc.get(
                upstream_id=mock_upstream.id,
                project_id=uuid.uuid4(),  # different project
                requesting_user_id=uuid.uuid4(),
            )

    async def test_nonexistent_upstream_raises_not_found(self) -> None:
        svc, mocks = _make_svc()
        mocks["upstream_repo"].get_by_id.return_value = None
        with pytest.raises(NotFoundError):
            await svc.get(
                upstream_id=uuid.uuid4(),
                project_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
            )


# ── update ────────────────────────────────────────────────────────────────────


class TestUpstreamServiceUpdate:
    async def test_member_can_update(self) -> None:
        project_id = uuid.uuid4()
        mock_upstream = _make_upstream(project_id=project_id)
        svc, mocks = _make_svc(
            membership=_make_membership(role="member"),
            upstream=mock_upstream,
        )
        await svc.update(
            upstream_id=mock_upstream.id,
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
            name="renamed-service",
        )
        mocks["upstream_repo"].save.assert_awaited_once()
        assert mock_upstream.name == "renamed-service"

    async def test_viewer_cannot_update(self) -> None:
        project_id = uuid.uuid4()
        mock_upstream = _make_upstream(project_id=project_id)
        svc, _ = _make_svc(
            membership=_make_membership(role="viewer"),
            upstream=mock_upstream,
        )
        with pytest.raises(ForbiddenError):
            await svc.update(
                upstream_id=mock_upstream.id,
                project_id=project_id,
                requesting_user_id=uuid.uuid4(),
                name="new name",
            )

    async def test_update_with_no_changes_calls_save(self) -> None:
        project_id = uuid.uuid4()
        mock_upstream = _make_upstream(project_id=project_id)
        svc, mocks = _make_svc(upstream=mock_upstream)
        await svc.update(
            upstream_id=mock_upstream.id,
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
        )
        # save still called even with no changes
        mocks["upstream_repo"].save.assert_awaited_once()

    async def test_partial_update_leaves_other_fields_unchanged(self) -> None:
        project_id = uuid.uuid4()
        mock_upstream = _make_upstream(project_id=project_id)
        original_url = mock_upstream.base_url
        svc, _ = _make_svc(upstream=mock_upstream)
        await svc.update(
            upstream_id=mock_upstream.id,
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
            name="new-name",
        )
        assert mock_upstream.base_url == original_url


# ── delete ────────────────────────────────────────────────────────────────────


class TestUpstreamServiceDelete:
    async def test_member_can_delete(self) -> None:
        project_id = uuid.uuid4()
        mock_upstream = _make_upstream(project_id=project_id)
        svc, mocks = _make_svc(
            membership=_make_membership(role="member"),
            upstream=mock_upstream,
        )
        await svc.delete(
            upstream_id=mock_upstream.id,
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
        )
        mocks["upstream_repo"].soft_delete.assert_awaited_once_with(mock_upstream)

    async def test_viewer_cannot_delete(self) -> None:
        project_id = uuid.uuid4()
        mock_upstream = _make_upstream(project_id=project_id)
        svc, _ = _make_svc(
            membership=_make_membership(role="viewer"),
            upstream=mock_upstream,
        )
        with pytest.raises(ForbiddenError):
            await svc.delete(
                upstream_id=mock_upstream.id,
                project_id=project_id,
                requesting_user_id=uuid.uuid4(),
            )
