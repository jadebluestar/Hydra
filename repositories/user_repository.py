from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_email(
        self,
        email: str,
        *,
        options: Sequence[Any] = (),
    ) -> User | None:
        """Look up an active user by email address (normalized to lowercase)."""
        stmt = self._base_select().where(User.email == email.strip().lower())
        for opt in options:
            stmt = stmt.options(opt)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
        full_name: str | None = None,
    ) -> User:
        user = User(
            email=email.strip().lower(),
            password_hash=password_hash,
            full_name=full_name,
        )
        return await self.save(user)

    async def update_last_login(self, user: User) -> None:
        user.last_login_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def soft_delete(self, user: User) -> None:
        user.soft_delete()
        await self._session.flush()

    async def email_exists(self, email: str) -> bool:
        """Return True if an active user with this email already exists."""
        stmt = (
            select(User.id)
            .where(User.email == email.strip().lower())
            .where(User.deleted_at.is_(None))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None
