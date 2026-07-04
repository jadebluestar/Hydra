from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.membership import OrganizationMembership
from models.organization import Organization
from repositories.base import BaseRepository


class OrganizationRepository(BaseRepository[Organization]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Organization)

    async def get_by_slug(
        self,
        slug: str,
        *,
        options: Sequence[Any] = (),
    ) -> Organization | None:
        stmt = self._base_select().where(Organization.slug == slug)
        for opt in options:
            stmt = stmt.options(opt)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        slug: str,
        plan: str = "free",
    ) -> Organization:
        org = Organization(name=name, slug=slug, plan=plan)
        return await self.save(org)

    async def list_for_user(self, user_id: uuid.UUID) -> list[Organization]:
        """
        Return all non-deleted organizations the user is a member of.

        Uses a JOIN through organization_memberships rather than loading
        memberships as a relationship — more efficient when you only need
        the org list, not the membership details.
        """
        stmt = (
            self._base_select()
            .join(
                OrganizationMembership,
                OrganizationMembership.organization_id == Organization.id,
            )
            .where(OrganizationMembership.user_id == user_id)
            .order_by(Organization.name)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def slug_exists(self, slug: str) -> bool:
        stmt = (
            select(Organization.id)
            .where(Organization.slug == slug)
            .where(Organization.deleted_at.is_(None))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def soft_delete(self, org: Organization) -> None:
        org.soft_delete()
        await self._session.flush()
