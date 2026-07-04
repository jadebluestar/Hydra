from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.project import Project
from repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Project)

    async def get_by_org_and_slug(
        self,
        org_id: uuid.UUID,
        slug: str,
        *,
        options: Sequence[Any] = (),
    ) -> Project | None:
        stmt = (
            self._base_select().where(Project.organization_id == org_id).where(Project.slug == slug)
        )
        for opt in options:
            stmt = stmt.options(opt)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_org(
        self,
        org_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Project]:
        stmt = (
            self._base_select()
            .where(Project.organization_id == org_id)
            .order_by(Project.name)
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        org_id: uuid.UUID,
        name: str,
        slug: str,
        description: str | None = None,
    ) -> Project:
        project = Project(
            organization_id=org_id,
            name=name,
            slug=slug,
            description=description,
        )
        return await self.save(project)

    async def slug_exists_in_org(self, org_id: uuid.UUID, slug: str) -> bool:
        stmt = (
            select(Project.id)
            .where(Project.organization_id == org_id)
            .where(Project.slug == slug)
            .where(Project.deleted_at.is_(None))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def soft_delete(self, project: Project) -> None:
        project.soft_delete()
        await self._session.flush()
