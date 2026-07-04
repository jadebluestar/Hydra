"""
Route Service.

Manages the lifecycle of routes within a project. A route maps an inbound
path prefix to an upstream backend and carries configuration for auth scopes,
method filtering, prefix stripping, and rate limiting.

Routes are the gateway's core primitive — they're loaded into the in-memory
trie at startup (Milestone 13). This service manages the configuration side;
the gateway proxy reads these via RouteRepository.list_active_with_upstream().

Key invariant enforced here:
  - The referenced upstream_id must belong to the same project as the route.
    This prevents cross-project upstream references, which would be a subtle
    data-leak vector if a user has write access to multiple projects.
"""

from __future__ import annotations

import uuid
from typing import Any

from core.exceptions import ForbiddenError, NotFoundError
from core.logging import get_logger
from domain.enums.permission import Permission
from domain.enums.role import Role
from domain.value_objects.route_path import RoutePath
from models.route import Route
from repositories.membership_repository import MembershipRepository
from repositories.project_repository import ProjectRepository
from repositories.route_repository import RouteRepository
from repositories.upstream_repository import UpstreamRepository
from security.rbac import require_permission

logger = get_logger(__name__)

# Sentinel: distinguishes "field not provided" from "field explicitly set to None".
# Used for nullable update params (required_scope, rate_limit_rpm) where None is
# a valid value meaning "remove this setting."
_UNSET: Any = object()


class RouteService:
    def __init__(
        self,
        *,
        route_repo: RouteRepository,
        upstream_repo: UpstreamRepository,
        project_repo: ProjectRepository,
        membership_repo: MembershipRepository,
    ) -> None:
        self._routes = route_repo
        self._upstreams = upstream_repo
        self._projects = project_repo
        self._memberships = membership_repo

    async def _require_permission(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        permission: Permission,
    ) -> None:
        project = await self._projects.get_by_id(project_id)
        if not project:
            raise ForbiddenError("Project not found or access denied")
        membership = await self._memberships.get_by_org_and_user(project.organization_id, user_id)
        if not membership:
            raise ForbiddenError("Access denied")
        require_permission(Role(membership.role), permission)

    async def _get_route_for_project(
        self,
        route_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> Route:
        route = await self._routes.get_by_id(route_id)
        if not route or route.project_id != project_id:
            raise NotFoundError("Route not found")
        return route

    async def _validate_upstream_in_project(
        self,
        upstream_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> None:
        upstream = await self._upstreams.get_by_id(upstream_id)
        if not upstream or upstream.project_id != project_id:
            raise NotFoundError("Upstream not found in this project")

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        name: str,
        path_prefix: str,
        upstream_id: uuid.UUID,
        methods: list[str] | None = None,
        required_scope: str | None = None,
        strip_prefix: bool = True,
        rate_limit_rpm: int | None = None,
        is_active: bool = True,
    ) -> Route:
        await self._require_permission(project_id, requesting_user_id, Permission.CREATE_ROUTE)
        normalized_path = RoutePath(path_prefix).value
        await self._validate_upstream_in_project(upstream_id, project_id)

        route = await self._routes.create(
            project_id=project_id,
            upstream_id=upstream_id,
            name=name,
            path_prefix=normalized_path,
            methods=methods or [],
            required_scope=required_scope,
            strip_prefix=strip_prefix,
            rate_limit_rpm=rate_limit_rpm,
            is_active=is_active,
        )
        logger.info(
            "route.created",
            route_id=str(route.id),
            path=normalized_path,
            project_id=str(project_id),
        )
        return route

    async def list(
        self,
        *,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Route]:
        await self._require_permission(project_id, requesting_user_id, Permission.VIEW_ROUTES)
        return await self._routes.list_by_project(
            project_id,
            active_only=active_only,
            limit=limit,
            offset=offset,
        )

    async def get(
        self,
        *,
        route_id: uuid.UUID,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
    ) -> Route:
        await self._require_permission(project_id, requesting_user_id, Permission.VIEW_ROUTES)
        return await self._get_route_for_project(route_id, project_id)

    async def update(
        self,
        *,
        route_id: uuid.UUID,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        name: str | None = None,
        path_prefix: str | None = None,
        upstream_id: uuid.UUID | None = None,
        methods: list[str] | None = None,
        required_scope: Any = _UNSET,
        strip_prefix: bool | None = None,
        rate_limit_rpm: Any = _UNSET,
        is_active: bool | None = None,
    ) -> Route:
        await self._require_permission(project_id, requesting_user_id, Permission.UPDATE_ROUTE)
        route = await self._get_route_for_project(route_id, project_id)

        if name is not None:
            route.name = name
        if path_prefix is not None:
            route.path_prefix = RoutePath(path_prefix).value
        if upstream_id is not None:
            await self._validate_upstream_in_project(upstream_id, project_id)
            route.upstream_id = upstream_id
        if methods is not None:
            route.methods = methods
        if required_scope is not _UNSET:
            route.required_scope = required_scope
        if strip_prefix is not None:
            route.strip_prefix = strip_prefix
        if rate_limit_rpm is not _UNSET:
            route.rate_limit_rpm = rate_limit_rpm
        if is_active is not None:
            route.is_active = is_active

        return await self._routes.save(route)

    async def delete(
        self,
        *,
        route_id: uuid.UUID,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
    ) -> None:
        await self._require_permission(project_id, requesting_user_id, Permission.DELETE_ROUTE)
        route = await self._get_route_for_project(route_id, project_id)
        await self._routes.soft_delete(route)
        logger.info("route.deleted", route_id=str(route_id))
