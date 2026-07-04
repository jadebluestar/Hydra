"""
Upstream Service.

Manages the lifecycle of upstream backend configurations within a project.
An upstream is a named backend service (URL + timeout + retry policy) that
routes can point to. Multiple routes can share one upstream.

Access model:
  - VIEW_ROUTES permission required to read (reuses route permission since
    upstreams and routes are always viewed together in the gateway config)
  - CREATE_UPSTREAM / UPDATE_UPSTREAM / DELETE_UPSTREAM for mutations
"""

from __future__ import annotations

import uuid

from core.exceptions import ForbiddenError, NotFoundError
from core.logging import get_logger
from domain.enums.permission import Permission
from domain.enums.role import Role
from models.upstream import Upstream
from repositories.membership_repository import MembershipRepository
from repositories.project_repository import ProjectRepository
from repositories.upstream_repository import UpstreamRepository
from security.rbac import require_permission

logger = get_logger(__name__)


class UpstreamService:
    def __init__(
        self,
        *,
        upstream_repo: UpstreamRepository,
        project_repo: ProjectRepository,
        membership_repo: MembershipRepository,
    ) -> None:
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
        membership = await self._memberships.get_by_org_and_user(
            project.organization_id, user_id
        )
        if not membership:
            raise ForbiddenError("Access denied")
        require_permission(Role(membership.role), permission)

    async def _get_upstream_for_project(
        self,
        upstream_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> Upstream:
        upstream = await self._upstreams.get_by_id(upstream_id)
        if not upstream or upstream.project_id != project_id:
            raise NotFoundError("Upstream not found")
        return upstream

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        name: str,
        base_url: str,
        timeout_seconds: int = 30,
        retries: int = 3,
    ) -> Upstream:
        await self._require_permission(
            project_id, requesting_user_id, Permission.CREATE_UPSTREAM
        )
        upstream = await self._upstreams.create(
            project_id=project_id,
            name=name,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            retries=retries,
        )
        logger.info(
            "upstream.created",
            upstream_id=str(upstream.id),
            project_id=str(project_id),
        )
        return upstream

    async def list(
        self,
        *,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Upstream]:
        await self._require_permission(
            project_id, requesting_user_id, Permission.VIEW_ROUTES
        )
        return await self._upstreams.list_by_project(
            project_id, limit=limit, offset=offset
        )

    async def get(
        self,
        *,
        upstream_id: uuid.UUID,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
    ) -> Upstream:
        await self._require_permission(
            project_id, requesting_user_id, Permission.VIEW_ROUTES
        )
        return await self._get_upstream_for_project(upstream_id, project_id)

    async def update(
        self,
        *,
        upstream_id: uuid.UUID,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        name: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
        retries: int | None = None,
    ) -> Upstream:
        await self._require_permission(
            project_id, requesting_user_id, Permission.UPDATE_UPSTREAM
        )
        upstream = await self._get_upstream_for_project(upstream_id, project_id)
        if name is not None:
            upstream.name = name
        if base_url is not None:
            upstream.base_url = base_url
        if timeout_seconds is not None:
            upstream.timeout_seconds = timeout_seconds
        if retries is not None:
            upstream.retries = retries
        return await self._upstreams.save(upstream)

    async def delete(
        self,
        *,
        upstream_id: uuid.UUID,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
    ) -> None:
        await self._require_permission(
            project_id, requesting_user_id, Permission.DELETE_UPSTREAM
        )
        upstream = await self._get_upstream_for_project(upstream_id, project_id)
        await self._upstreams.soft_delete(upstream)
        logger.info("upstream.deleted", upstream_id=str(upstream_id))
