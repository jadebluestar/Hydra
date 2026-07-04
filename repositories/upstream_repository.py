from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from models.upstream import Upstream
from repositories.base import BaseRepository


class UpstreamRepository(BaseRepository[Upstream]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Upstream)

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
        options: Sequence[Any] = (),
    ) -> list[Upstream]:
        stmt = (
            self._base_select()
            .where(Upstream.project_id == project_id)
            .order_by(Upstream.name)
            .limit(limit)
            .offset(offset)
        )
        for opt in options:
            stmt = stmt.options(opt)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        name: str,
        base_url: str,
        timeout_seconds: int = 30,
        retries: int = 3,
    ) -> Upstream:
        upstream = Upstream(
            project_id=project_id,
            name=name,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            retries=retries,
        )
        return await self.save(upstream)

    async def soft_delete(self, upstream: Upstream) -> None:
        upstream.soft_delete()
        await self._session.flush()
