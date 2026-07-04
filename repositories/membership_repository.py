from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.membership import OrganizationMembership
from models.user import User
from repositories.base import BaseRepository


class MembershipRepository(BaseRepository[OrganizationMembership]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, OrganizationMembership)

    async def get_by_org_and_user(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        options: Sequence[Any] = (),
    ) -> OrganizationMembership | None:
        stmt = (
            self._base_select()
            .where(OrganizationMembership.organization_id == org_id)
            .where(OrganizationMembership.user_id == user_id)
        )
        for opt in options:
            stmt = stmt.options(opt)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_org(
        self,
        org_id: uuid.UUID,
        *,
        options: Sequence[Any] = (),
    ) -> list[OrganizationMembership]:
        stmt = (
            self._base_select()
            .where(OrganizationMembership.organization_id == org_id)
            .order_by(OrganizationMembership.created_at)
        )
        for opt in options:
            stmt = stmt.options(opt)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        options: Sequence[Any] = (),
    ) -> list[OrganizationMembership]:
        stmt = (
            self._base_select()
            .where(OrganizationMembership.user_id == user_id)
        )
        for opt in options:
            stmt = stmt.options(opt)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
        invited_by_id: uuid.UUID | None = None,
    ) -> OrganizationMembership:
        membership = OrganizationMembership(
            organization_id=org_id,
            user_id=user_id,
            role=role,
            invited_by_id=invited_by_id,
        )
        return await self.save(membership)

    async def delete(self, membership: OrganizationMembership) -> None:
        """Hard delete — membership revocation leaves no ghost record."""
        await self.hard_delete(membership)

    async def count_by_org(self, org_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(OrganizationMembership)
            .where(OrganizationMembership.organization_id == org_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()
