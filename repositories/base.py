"""
Generic async repository base.

All model-specific repositories extend this class, inheriting standard
CRUD operations and consistent soft-delete filtering.

Pattern overview:
  - Services create a repository per request, passing the AsyncSession
  - Repositories flush but never commit (session lifecycle owned by get_db())
  - Soft-delete models are filtered automatically in _base_select()
  - Relationship loading is explicit via `options` parameter
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from database.base import HydraSoftDeleteBase


class BaseRepository[ModelT]:
    def __init__(self, session: AsyncSession, model_class: type[ModelT]) -> None:
        self._session = session
        self._model = model_class
        self._is_soft_delete = issubclass(model_class, HydraSoftDeleteBase)

    def _base_select(self) -> Select[tuple[ModelT]]:
        """
        Base SELECT for this model.

        Automatically filters deleted_at IS NULL for soft-delete models.
        All query-building methods start from this so filtering is never missed.
        """
        stmt: Select[tuple[ModelT]] = select(self._model)  # type: ignore[arg-type]
        if self._is_soft_delete:
            stmt = stmt.where(self._model.deleted_at.is_(None))  # type: ignore[attr-defined]
        return stmt

    async def get_by_id(
        self,
        id: uuid.UUID,
        *,
        options: Sequence[Any] = (),
    ) -> ModelT | None:
        """
        Fetch one record by primary key, or None if not found (or soft-deleted).

        Args:
            options: SQLAlchemy loader options, e.g.:
                     [selectinload(User.memberships), joinedload(User.org)]
        """
        stmt = self._base_select().where(self._model.id == id)  # type: ignore[attr-defined]
        for opt in options:
            stmt = stmt.options(opt)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        options: Sequence[Any] = (),
    ) -> list[ModelT]:
        """
        Fetch a paginated list of records.

        Default limit=50 prevents accidental full-table scans. Services
        should always pass an explicit limit.
        """
        stmt = self._base_select().limit(limit).offset(offset)
        for opt in options:
            stmt = stmt.options(opt)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        """Count of non-deleted records (excludes soft-deleted rows)."""
        stmt = select(func.count()).select_from(self._base_select().subquery())
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def save(self, obj: ModelT) -> ModelT:
        """
        Persist a new or modified object.

        For new objects: adds to the session and flushes so that
        server_default columns (created_at, updated_at) are populated
        and the object can be returned with all fields set.

        For existing objects: SQLAlchemy tracks attribute changes automatically
        via the unit-of-work pattern. Flushing sends pending UPDATEs.

        Does NOT commit. The calling request's get_db() dependency commits.
        """
        self._session.add(obj)
        await self._session.flush()
        await self._session.refresh(obj)
        return obj

    async def hard_delete(self, obj: ModelT) -> None:
        """
        Permanently delete a record from the database.

        Only use for records that truly should be erased (e.g., memberships,
        which are hard-deleted). For most entities, use soft_delete() instead.
        """
        await self._session.delete(obj)
        await self._session.flush()
