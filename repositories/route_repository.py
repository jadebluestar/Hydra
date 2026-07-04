from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.route import Route
from models.upstream import Upstream
from repositories.base import BaseRepository


class RouteRepository(BaseRepository[Route]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Route)

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
        options: Sequence[Any] = (),
    ) -> list[Route]:
        stmt = (
            self._base_select()
            .where(Route.project_id == project_id)
            .order_by(Route.path_prefix)
            .limit(limit)
            .offset(offset)
        )
        if active_only:
            stmt = stmt.where(Route.is_active.is_(True))
        for opt in options:
            stmt = stmt.options(opt)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_active_with_upstream(
        self,
        project_id: uuid.UUID,
    ) -> list[Route]:
        """
        Load all active routes for a project, with their upstream pre-loaded.

        This is the query that populates the in-memory trie at startup and
        on route changes. It must eager-load the upstream because the gateway
        pipeline needs upstream.base_url and upstream.timeout_seconds to proxy
        the request — accessing lazy relationships fails in async context.

        selectinload emits:
          SELECT * FROM routes WHERE project_id = ? AND is_active = TRUE
          SELECT * FROM upstreams WHERE id IN (?, ?, ...)  ← second query

        This is better than joinedload here because routes can share an
        upstream — a JOIN would duplicate the upstream row for every route.
        """
        stmt = (
            self._base_select()
            .where(Route.project_id == project_id)
            .where(Route.is_active.is_(True))
            .options(selectinload(Route.upstream))
            .order_by(Route.path_prefix)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        upstream_id: uuid.UUID,
        name: str,
        path_prefix: str,
        methods: list[str] | None = None,
        required_scope: str | None = None,
        strip_prefix: bool = True,
        rate_limit_rpm: int | None = None,
        is_active: bool = True,
    ) -> Route:
        route = Route(
            project_id=project_id,
            upstream_id=upstream_id,
            name=name,
            path_prefix=path_prefix,
            methods=methods or [],
            required_scope=required_scope,
            strip_prefix=strip_prefix,
            rate_limit_rpm=rate_limit_rpm,
            is_active=is_active,
        )
        return await self.save(route)

    async def set_active(self, route: Route, *, active: bool) -> None:
        route.is_active = active
        await self._session.flush()

    async def soft_delete(self, route: Route) -> None:
        route.soft_delete()
        await self._session.flush()
