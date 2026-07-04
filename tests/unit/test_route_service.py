"""Unit tests for RouteService — no DB required."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import ForbiddenError, NotFoundError
from services.route_service import RouteService


def _make_membership(role: str = "member") -> MagicMock:
    m = MagicMock()
    m.role = role
    return m


def _make_upstream(project_id: uuid.UUID | None = None) -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.project_id = project_id or uuid.uuid4()
    return u


def _make_route(project_id: uuid.UUID | None = None) -> MagicMock:
    r = MagicMock()
    r.id = uuid.uuid4()
    r.project_id = project_id or uuid.uuid4()
    r.path_prefix = "/api/v1/users"
    r.upstream_id = uuid.uuid4()
    r.methods = []
    r.required_scope = None
    r.strip_prefix = True
    r.rate_limit_rpm = None
    r.is_active = True
    return r


def _make_project(org_id: uuid.UUID | None = None) -> MagicMock:
    p = MagicMock()
    p.id = uuid.uuid4()
    p.organization_id = org_id or uuid.uuid4()
    return p


def _make_svc(
    *,
    membership: MagicMock | None = None,
    route: MagicMock | None = None,
    upstream: MagicMock | None = None,
    upstream_not_found: bool = False,
) -> tuple[RouteService, dict]:
    mock_project = _make_project()
    mock_route = route or _make_route(project_id=mock_project.id)
    mock_upstream = upstream or _make_upstream(project_id=mock_project.id)
    mock_membership = membership or _make_membership(role="member")

    project_repo = AsyncMock()
    project_repo.get_by_id.return_value = mock_project

    membership_repo = AsyncMock()
    membership_repo.get_by_org_and_user.return_value = mock_membership

    route_repo = AsyncMock()
    route_repo.get_by_id.return_value = mock_route
    route_repo.create.return_value = mock_route
    route_repo.save.return_value = mock_route
    route_repo.list_by_project.return_value = [mock_route]
    route_repo.soft_delete.return_value = None

    upstream_repo = AsyncMock()
    upstream_repo.get_by_id.return_value = None if upstream_not_found else mock_upstream

    svc = RouteService(
        route_repo=route_repo,
        upstream_repo=upstream_repo,
        project_repo=project_repo,
        membership_repo=membership_repo,
    )
    return svc, {
        "route": mock_route,
        "upstream": mock_upstream,
        "project": mock_project,
        "route_repo": route_repo,
        "upstream_repo": upstream_repo,
        "membership_repo": membership_repo,
    }


# ── create ────────────────────────────────────────────────────────────────────


class TestRouteServiceCreate:
    async def test_member_can_create(self) -> None:
        svc, mocks = _make_svc(membership=_make_membership(role="member"))
        project_id = mocks["project"].id
        # upstream must belong to same project
        mocks["upstream"].project_id = project_id

        route = await svc.create(
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
            name="users route",
            path_prefix="/api/users",
            upstream_id=mocks["upstream"].id,
        )
        assert route is not None

    async def test_viewer_cannot_create(self) -> None:
        svc, mocks = _make_svc(membership=_make_membership(role="viewer"))
        with pytest.raises(ForbiddenError):
            await svc.create(
                project_id=mocks["project"].id,
                requesting_user_id=uuid.uuid4(),
                name="x",
                path_prefix="/x",
                upstream_id=uuid.uuid4(),
            )

    async def test_non_member_cannot_create(self) -> None:
        svc, mocks = _make_svc()
        mocks["membership_repo"].get_by_org_and_user.return_value = None
        with pytest.raises(ForbiddenError):
            await svc.create(
                project_id=mocks["project"].id,
                requesting_user_id=uuid.uuid4(),
                name="x",
                path_prefix="/x",
                upstream_id=uuid.uuid4(),
            )

    async def test_upstream_from_different_project_raises_not_found(self) -> None:
        svc, mocks = _make_svc()
        project_id = mocks["project"].id
        # upstream belongs to a different project
        mocks["upstream"].project_id = uuid.uuid4()

        with pytest.raises(NotFoundError, match="Upstream not found in this project"):
            await svc.create(
                project_id=project_id,
                requesting_user_id=uuid.uuid4(),
                name="x",
                path_prefix="/x",
                upstream_id=mocks["upstream"].id,
            )

    async def test_nonexistent_upstream_raises_not_found(self) -> None:
        svc, mocks = _make_svc(upstream_not_found=True)
        with pytest.raises(NotFoundError):
            await svc.create(
                project_id=mocks["project"].id,
                requesting_user_id=uuid.uuid4(),
                name="x",
                path_prefix="/x",
                upstream_id=uuid.uuid4(),
            )

    async def test_path_prefix_is_normalized(self) -> None:
        svc, mocks = _make_svc()
        project_id = mocks["project"].id
        mocks["upstream"].project_id = project_id

        await svc.create(
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
            name="users",
            path_prefix="/api/users/",  # trailing slash
            upstream_id=mocks["upstream"].id,
        )
        call_kwargs = mocks["route_repo"].create.call_args.kwargs
        # RoutePath normalizes trailing slash
        assert call_kwargs["path_prefix"] == "/api/users"

    async def test_invalid_path_raises_value_error(self) -> None:
        svc, mocks = _make_svc()
        with pytest.raises(ValueError):
            await svc.create(
                project_id=mocks["project"].id,
                requesting_user_id=uuid.uuid4(),
                name="x",
                path_prefix="no-leading-slash",
                upstream_id=uuid.uuid4(),
            )

    async def test_create_passes_methods_to_repo(self) -> None:
        svc, mocks = _make_svc()
        project_id = mocks["project"].id
        mocks["upstream"].project_id = project_id

        await svc.create(
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
            name="users",
            path_prefix="/api/users",
            upstream_id=mocks["upstream"].id,
            methods=["GET", "POST"],
        )
        call_kwargs = mocks["route_repo"].create.call_args.kwargs
        assert call_kwargs["methods"] == ["GET", "POST"]


# ── list ─────────────────────────────────────────────────────────────────────


class TestRouteServiceList:
    async def test_viewer_can_list(self) -> None:
        svc, mocks = _make_svc(membership=_make_membership(role="viewer"))
        routes = await svc.list(
            project_id=mocks["project"].id,
            requesting_user_id=uuid.uuid4(),
        )
        assert len(routes) == 1

    async def test_non_member_cannot_list(self) -> None:
        svc, mocks = _make_svc()
        mocks["membership_repo"].get_by_org_and_user.return_value = None
        with pytest.raises(ForbiddenError):
            await svc.list(
                project_id=mocks["project"].id,
                requesting_user_id=uuid.uuid4(),
            )

    async def test_active_only_is_passed_to_repo(self) -> None:
        svc, mocks = _make_svc()
        await svc.list(
            project_id=mocks["project"].id,
            requesting_user_id=uuid.uuid4(),
            active_only=False,
        )
        mocks["route_repo"].list_by_project.assert_awaited_once()
        call_kwargs = mocks["route_repo"].list_by_project.call_args.kwargs
        assert call_kwargs["active_only"] is False


# ── get ──────────────────────────────────────────────────────────────────────


class TestRouteServiceGet:
    async def test_viewer_can_get(self) -> None:
        project_id = uuid.uuid4()
        mock_route = _make_route(project_id=project_id)
        svc, mocks = _make_svc(
            membership=_make_membership(role="viewer"),
            route=mock_route,
        )
        result = await svc.get(
            route_id=mock_route.id,
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
        )
        assert result is mock_route

    async def test_route_from_different_project_raises_not_found(self) -> None:
        mock_route = _make_route(project_id=uuid.uuid4())
        svc, mocks = _make_svc(route=mock_route)
        with pytest.raises(NotFoundError):
            await svc.get(
                route_id=mock_route.id,
                project_id=uuid.uuid4(),  # different project
                requesting_user_id=uuid.uuid4(),
            )

    async def test_nonexistent_route_raises_not_found(self) -> None:
        svc, mocks = _make_svc()
        mocks["route_repo"].get_by_id.return_value = None
        with pytest.raises(NotFoundError):
            await svc.get(
                route_id=uuid.uuid4(),
                project_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
            )


# ── update ────────────────────────────────────────────────────────────────────


class TestRouteServiceUpdate:
    async def test_member_can_update_name(self) -> None:
        project_id = uuid.uuid4()
        mock_route = _make_route(project_id=project_id)
        svc, mocks = _make_svc(
            membership=_make_membership(role="member"),
            route=mock_route,
        )
        await svc.update(
            route_id=mock_route.id,
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
            name="renamed",
        )
        assert mock_route.name == "renamed"
        mocks["route_repo"].save.assert_awaited_once()

    async def test_viewer_cannot_update(self) -> None:
        project_id = uuid.uuid4()
        mock_route = _make_route(project_id=project_id)
        svc, _ = _make_svc(
            membership=_make_membership(role="viewer"),
            route=mock_route,
        )
        with pytest.raises(ForbiddenError):
            await svc.update(
                route_id=mock_route.id,
                project_id=project_id,
                requesting_user_id=uuid.uuid4(),
                name="x",
            )

    async def test_update_required_scope_to_none_clears_it(self) -> None:
        project_id = uuid.uuid4()
        mock_route = _make_route(project_id=project_id)
        mock_route.required_scope = "gateway:read"
        svc, mocks = _make_svc(route=mock_route)

        # Passing required_scope=None explicitly should clear the scope
        await svc.update(
            route_id=mock_route.id,
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
            required_scope=None,
        )
        assert mock_route.required_scope is None

    async def test_not_passing_required_scope_leaves_it_unchanged(self) -> None:
        project_id = uuid.uuid4()
        mock_route = _make_route(project_id=project_id)
        mock_route.required_scope = "gateway:read"
        svc, mocks = _make_svc(route=mock_route)

        # Not passing required_scope at all — should leave it as-is
        await svc.update(
            route_id=mock_route.id,
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
            name="new-name",
        )
        # required_scope is untouched because _UNSET sentinel was used
        assert mock_route.required_scope == "gateway:read"

    async def test_update_upstream_validates_project_ownership(self) -> None:
        project_id = uuid.uuid4()
        mock_route = _make_route(project_id=project_id)
        # upstream belongs to a different project
        other_upstream = _make_upstream(project_id=uuid.uuid4())
        svc, mocks = _make_svc(route=mock_route, upstream=other_upstream)
        mocks["upstream_repo"].get_by_id.return_value = other_upstream

        with pytest.raises(NotFoundError, match="Upstream not found in this project"):
            await svc.update(
                route_id=mock_route.id,
                project_id=project_id,
                requesting_user_id=uuid.uuid4(),
                upstream_id=other_upstream.id,
            )

    async def test_path_prefix_is_normalized_on_update(self) -> None:
        project_id = uuid.uuid4()
        mock_route = _make_route(project_id=project_id)
        svc, mocks = _make_svc(route=mock_route)
        await svc.update(
            route_id=mock_route.id,
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
            path_prefix="/api/users/",
        )
        assert mock_route.path_prefix == "/api/users"


# ── delete ────────────────────────────────────────────────────────────────────


class TestRouteServiceDelete:
    async def test_member_can_delete(self) -> None:
        project_id = uuid.uuid4()
        mock_route = _make_route(project_id=project_id)
        svc, mocks = _make_svc(
            membership=_make_membership(role="member"),
            route=mock_route,
        )
        await svc.delete(
            route_id=mock_route.id,
            project_id=project_id,
            requesting_user_id=uuid.uuid4(),
        )
        mocks["route_repo"].soft_delete.assert_awaited_once_with(mock_route)

    async def test_viewer_cannot_delete(self) -> None:
        project_id = uuid.uuid4()
        mock_route = _make_route(project_id=project_id)
        svc, _ = _make_svc(
            membership=_make_membership(role="viewer"),
            route=mock_route,
        )
        with pytest.raises(ForbiddenError):
            await svc.delete(
                route_id=mock_route.id,
                project_id=project_id,
                requesting_user_id=uuid.uuid4(),
            )

    async def test_nonexistent_route_raises_not_found(self) -> None:
        svc, mocks = _make_svc()
        mocks["route_repo"].get_by_id.return_value = None
        with pytest.raises(NotFoundError):
            await svc.delete(
                route_id=uuid.uuid4(),
                project_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
            )
