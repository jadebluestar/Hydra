"""
Analytics Service.

Provides access to request log data for gateway operators.
Access follows the same project membership model as other services —
VIEW_ANALYTICS permission (held by all roles including VIEWER) is required.

All methods are read-only: this service never mutates request logs.
Logs are written exclusively by the gateway background task (gateway/logger.py).
"""

from __future__ import annotations

import uuid
from typing import Any

from core.exceptions import ForbiddenError
from domain.enums.permission import Permission
from domain.enums.role import Role
from models.request_log import RequestLog
from repositories.membership_repository import MembershipRepository
from repositories.project_repository import ProjectRepository
from repositories.request_log_repository import RequestLogRepository
from security.rbac import require_permission


class AnalyticsService:
    def __init__(
        self,
        *,
        log_repo: RequestLogRepository,
        project_repo: ProjectRepository,
        membership_repo: MembershipRepository,
    ) -> None:
        self._logs = log_repo
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

    async def get_summary(
        self,
        *,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        hours: int = 24,
    ) -> dict[str, Any]:
        await self._require_permission(project_id, requesting_user_id, Permission.VIEW_ANALYTICS)
        return await self._logs.get_summary(project_id, hours=hours)

    async def list_requests(
        self,
        *,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RequestLog]:
        await self._require_permission(project_id, requesting_user_id, Permission.VIEW_ANALYTICS)
        return await self._logs.list_by_project(project_id, limit=limit, offset=offset)
