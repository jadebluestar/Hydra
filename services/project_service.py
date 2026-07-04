from __future__ import annotations

import uuid

from core.exceptions import ConflictError, ForbiddenError
from core.logging import get_logger
from domain.enums.permission import Permission
from domain.enums.role import Role
from models.project import Project
from repositories.membership_repository import MembershipRepository
from repositories.project_repository import ProjectRepository
from security.rbac import require_permission
from utils.slugify import slugify

logger = get_logger(__name__)


class ProjectService:
    def __init__(
        self,
        *,
        project_repo: ProjectRepository,
        membership_repo: MembershipRepository,
    ) -> None:
        self._projects = project_repo
        self._memberships = membership_repo

    async def _require_permission(
        self,
        project: Project,
        user_id: uuid.UUID,
        permission: Permission,
    ) -> None:
        """
        Verify the user has the given permission in the project's organization.

        Permission is always determined by the org-level role — there are no
        project-level roles in v1. A user who is ADMIN in the org is ADMIN
        for all of that org's projects.
        """
        membership = await self._memberships.get_by_org_and_user(project.organization_id, user_id)
        if not membership:
            raise ForbiddenError("Access denied")
        require_permission(Role(membership.role), permission)

    async def _get_project_for_user(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Project:
        """
        Load a project and verify the user is a member of its org.

        Returns ForbiddenError rather than NotFoundError intentionally —
        prevents project ID enumeration by non-members.
        """
        project = await self._projects.get_by_id(project_id)
        if not project:
            raise ForbiddenError("Project not found or access denied")
        membership = await self._memberships.get_by_org_and_user(project.organization_id, user_id)
        if not membership:
            raise ForbiddenError("Project not found or access denied")
        return project

    async def create(
        self,
        *,
        org_id: uuid.UUID,
        name: str,
        slug: str | None,
        description: str | None,
        requesting_user_id: uuid.UUID,
    ) -> Project:
        membership = await self._memberships.get_by_org_and_user(org_id, requesting_user_id)
        if not membership:
            raise ForbiddenError("You are not a member of this organization")
        require_permission(Role(membership.role), Permission.CREATE_PROJECT)

        resolved_slug = slug or slugify(name)
        if not resolved_slug:
            raise ConflictError("Cannot generate a valid slug from this name")

        if await self._projects.slug_exists_in_org(org_id, resolved_slug):
            raise ConflictError(
                f"A project with slug '{resolved_slug}' already exists in this organization"
            )

        project = await self._projects.create(
            org_id=org_id,
            name=name,
            slug=resolved_slug,
            description=description,
        )
        logger.info("project.created", project_id=str(project.id), slug=resolved_slug)
        return project

    async def get(
        self,
        *,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
    ) -> Project:
        return await self._get_project_for_user(project_id, requesting_user_id)

    async def list_by_org(
        self,
        *,
        org_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Project]:
        membership = await self._memberships.get_by_org_and_user(org_id, requesting_user_id)
        if not membership:
            raise ForbiddenError("You are not a member of this organization")
        require_permission(Role(membership.role), Permission.VIEW_PROJECT)
        return await self._projects.list_by_org(org_id, limit=limit, offset=offset)

    async def update(
        self,
        *,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        name: str | None = None,
        description: str | None = None,
    ) -> Project:
        project = await self._get_project_for_user(project_id, requesting_user_id)
        await self._require_permission(project, requesting_user_id, Permission.UPDATE_PROJECT)

        if name is not None:
            project.name = name
        if description is not None:
            project.description = description

        await self._projects.save(project)
        logger.info("project.updated", project_id=str(project_id))
        return project

    async def delete(
        self,
        *,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
    ) -> None:
        project = await self._get_project_for_user(project_id, requesting_user_id)
        await self._require_permission(project, requesting_user_id, Permission.DELETE_PROJECT)
        await self._projects.soft_delete(project)
        logger.info("project.deleted", project_id=str(project_id))
