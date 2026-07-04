"""
API Key Service.

Manages the lifecycle of project API keys: creation, listing, revocation,
and verification (used by the gateway in Milestone 11+).

Key design decisions:
  - SHA-256 hashing (not Argon2) — see utils/api_key.py for rationale
  - Full key returned exactly once on creation
  - Prefix-indexed lookup for the gateway hot path
  - Revocation is soft (revoked_at timestamp), not hard-delete — keeps audit trail
"""

from __future__ import annotations

import uuid
from datetime import datetime

from core.exceptions import ForbiddenError, NotFoundError
from core.logging import get_logger
from domain.enums.permission import Permission
from domain.enums.role import Role
from models.api_key import APIKey
from repositories.api_key_repository import APIKeyRepository
from repositories.membership_repository import MembershipRepository
from repositories.project_repository import ProjectRepository
from security.rbac import require_permission
from security.scopes import validate_requested_scopes
from utils.api_key import extract_prefix, generate_api_key, verify_key

logger = get_logger(__name__)


class APIKeyService:
    def __init__(
        self,
        *,
        api_key_repo: APIKeyRepository,
        project_repo: ProjectRepository,
        membership_repo: MembershipRepository,
    ) -> None:
        self._keys = api_key_repo
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
        membership = await self._memberships.get_by_org_and_user(
            project.organization_id, user_id
        )
        if not membership:
            raise ForbiddenError("Access denied")
        require_permission(Role(membership.role), permission)

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        name: str,
        scopes: list[str],
        expires_at: datetime | None = None,
    ) -> tuple[APIKey, str]:
        """
        Create a new API key and return (model, plaintext_key).

        The plaintext key is returned exactly once — it cannot be recovered
        later because only the SHA-256 hash is stored. The caller must return
        it to the user immediately.

        validate_requested_scopes raises ValueError for unknown scope strings.
        The router's Pydantic schema catches invalid scopes before we get here,
        but we validate again in the service as defense-in-depth.
        """
        await self._require_permission(project_id, requesting_user_id, Permission.CREATE_API_KEY)
        validate_requested_scopes(scopes)

        full_key, key_prefix, key_hash = generate_api_key(env="live")

        api_key = await self._keys.create(
            project_id=project_id,
            created_by_id=requesting_user_id,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            scopes=scopes,
            expires_at=expires_at,
        )

        logger.info(
            "api_key.created",
            key_id=str(api_key.id),
            project_id=str(project_id),
            prefix=key_prefix,
        )
        return api_key, full_key

    async def list(
        self,
        *,
        project_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        include_revoked: bool = False,
    ) -> list[APIKey]:
        await self._require_permission(project_id, requesting_user_id, Permission.VIEW_API_KEYS)
        return await self._keys.list_by_project(
            project_id, include_revoked=include_revoked
        )

    async def revoke(
        self,
        *,
        key_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
    ) -> None:
        """
        Revoke an API key by setting its revoked_at timestamp.

        The key remains in the database for audit trail purposes.
        The gateway checks is_active on every request, so revocation
        takes effect immediately on the next request (no cache invalidation
        needed until Milestone 17 adds Redis caching).
        """
        api_key = await self._keys.get_by_id(key_id)
        if not api_key:
            raise NotFoundError("API key not found")

        await self._require_permission(
            api_key.project_id, requesting_user_id, Permission.DELETE_API_KEY
        )

        if api_key.is_revoked:
            return  # idempotent — already revoked, no-op

        await self._keys.revoke(api_key)
        logger.info("api_key.revoked", key_id=str(key_id))

    async def verify(self, raw_key: str) -> APIKey | None:
        """
        Verify a raw API key string and return the matching APIKey record.

        Called by the gateway on every authenticated request. Returns None
        if the key is invalid, expired, or revoked rather than raising —
        the gateway handles the 401 response directly.

        This is the read hot path:
          1. Extract prefix (O(1), no crypto)
          2. DB lookup by prefix — indexed, returns ≤ a handful of rows
          3. SHA-256 verify against each candidate — microseconds

        Milestone 17 will add a Redis cache layer in front of this to
        eliminate the DB round-trip for frequently-used keys.
        """
        prefix = extract_prefix(raw_key)
        candidates = await self._keys.get_candidates_by_prefix(prefix)

        for candidate in candidates:
            if verify_key(raw_key, candidate.key_hash):
                return candidate if candidate.is_active else None

        return None
