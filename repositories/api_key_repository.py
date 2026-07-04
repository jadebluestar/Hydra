from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.api_key import APIKey
from repositories.base import BaseRepository


class APIKeyRepository(BaseRepository[APIKey]):
    """
    Repository for API key records.

    IMPORTANT: this repository DOES NOT handle key generation, hashing, or
    verification — those are responsibilities of the APIKeyService.
    Here we only store and retrieve key metadata.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, APIKey)

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        include_revoked: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[APIKey]:
        stmt = (
            self._base_select()
            .where(APIKey.project_id == project_id)
            .order_by(APIKey.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if not include_revoked:
            stmt = stmt.where(APIKey.revoked_at.is_(None))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_candidates_by_prefix(
        self,
        key_prefix: str,
    ) -> list[APIKey]:
        """
        Return all active (non-revoked, non-expired) keys matching a prefix.

        Why return a list rather than one record?
          Key prefixes are not globally unique — different projects can produce
          keys with the same prefix by chance. The gateway verifies the full
          hash against all candidates and returns the match.

          In practice, prefix collisions are astronomically rare given a 16-char
          prefix of a cryptographically random key. The list will almost always
          have exactly one element.

        The gateway calls this on every authenticated request, so this query
        runs on the hot path. The index on key_prefix makes it fast.
        """
        now = datetime.now(UTC)
        stmt = (
            select(APIKey)
            .where(APIKey.key_prefix == key_prefix)
            .where(APIKey.revoked_at.is_(None))
            .where((APIKey.expires_at.is_(None)) | (APIKey.expires_at > now))
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        created_by_id: uuid.UUID | None,
        name: str,
        key_prefix: str,
        key_hash: str,
        scopes: list[str],
        expires_at: datetime | None = None,
    ) -> APIKey:
        api_key = APIKey(
            project_id=project_id,
            created_by_id=created_by_id,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            scopes=scopes,
            expires_at=expires_at,
        )
        return await self.save(api_key)

    async def revoke(self, api_key: APIKey) -> None:
        api_key.revoked_at = datetime.now(UTC)
        await self._session.flush()

    async def update_last_used(self, api_key: APIKey) -> None:
        """
        Record that this key was used just now.

        Called on every authenticated gateway request. This is a write on the
        hot path — consider debouncing in future (update at most once per minute
        per key) if it becomes a bottleneck. For now correctness > performance.
        """
        api_key.last_used_at = datetime.now(UTC)
        await self._session.flush()
