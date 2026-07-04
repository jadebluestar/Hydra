"""Unit tests for AnalyticsService — no DB required."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import ForbiddenError
from services.analytics_service import AnalyticsService


def _make_membership(role: str = "viewer") -> MagicMock:
    m = MagicMock()
    m.role = role
    return m


def _make_project() -> MagicMock:
    p = MagicMock()
    p.id = uuid.uuid4()
    p.organization_id = uuid.uuid4()
    return p


def _make_summary() -> dict:
    return {
        "total_requests": 100,
        "success_count": 90,
        "error_count": 10,
        "rate_limited_count": 5,
        "avg_latency_ms": 42.0,
        "period_hours": 24,
    }


def _make_svc(
    *,
    membership: MagicMock | None = None,
    summary: dict | None = None,
    logs: list | None = None,
) -> tuple[AnalyticsService, dict]:
    mock_project = _make_project()
    mock_membership = membership or _make_membership(role="viewer")

    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = mock_project

    membership_repo = AsyncMock()
    membership_repo.get_by_org_and_user.return_value = mock_membership

    log_repo = AsyncMock()
    log_repo.get_summary.return_value = summary or _make_summary()
    log_repo.list_by_project.return_value = logs or []

    svc = AnalyticsService(
        log_repo=log_repo,
        project_repo=project_repo,
        membership_repo=membership_repo,
    )
    return svc, {
        "project": mock_project,
        "log_repo": log_repo,
        "membership_repo": membership_repo,
    }


class TestAnalyticsSummary:
    async def test_viewer_can_get_summary(self) -> None:
        svc, mocks = _make_svc(membership=_make_membership(role="viewer"))
        result = await svc.get_summary(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
        )
        assert result["total_requests"] == 100
        assert result["success_count"] == 90

    async def test_non_member_cannot_get_summary(self) -> None:
        svc, mocks = _make_svc()
        mocks["membership_repo"].get_by_org_and_user.return_value = None
        with pytest.raises(ForbiddenError):
            await svc.get_summary(
                project_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
            )

    async def test_unknown_project_raises_forbidden(self) -> None:
        svc, mocks = _make_svc()
        svc._projects.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(ForbiddenError):
            await svc.get_summary(
                project_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
            )

    async def test_hours_passed_to_repo(self) -> None:
        svc, mocks = _make_svc()
        await svc.get_summary(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
            hours=48,
        )
        mocks["log_repo"].get_summary.assert_awaited_once()
        call_kwargs = mocks["log_repo"].get_summary.call_args.kwargs
        assert call_kwargs["hours"] == 48

    async def test_default_hours_is_24(self) -> None:
        svc, mocks = _make_svc()
        await svc.get_summary(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
        )
        call_kwargs = mocks["log_repo"].get_summary.call_args.kwargs
        assert call_kwargs["hours"] == 24


class TestAnalyticsListRequests:
    async def test_viewer_can_list(self) -> None:
        mock_log = MagicMock()
        svc, mocks = _make_svc(logs=[mock_log])
        results = await svc.list_requests(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
        )
        assert len(results) == 1
        assert results[0] is mock_log

    async def test_non_member_cannot_list(self) -> None:
        svc, mocks = _make_svc()
        mocks["membership_repo"].get_by_org_and_user.return_value = None
        with pytest.raises(ForbiddenError):
            await svc.list_requests(
                project_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
            )

    async def test_pagination_passed_to_repo(self) -> None:
        svc, mocks = _make_svc()
        await svc.list_requests(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
            limit=10,
            offset=20,
        )
        call_kwargs = mocks["log_repo"].list_by_project.call_args.kwargs
        assert call_kwargs["limit"] == 10
        assert call_kwargs["offset"] == 20

    async def test_admin_can_list(self) -> None:
        svc, mocks = _make_svc(membership=_make_membership(role="admin"))
        await svc.list_requests(
            project_id=uuid.uuid4(),
            requesting_user_id=uuid.uuid4(),
        )
        mocks["log_repo"].list_by_project.assert_awaited_once()
