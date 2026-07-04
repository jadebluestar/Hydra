"""
Organization Service.

Manages the full lifecycle of organizations and their memberships.
All permission checks happen here — routers never check roles directly.

Dependency pattern:
  OrganizationService is constructed per-request in the router, receiving
  concrete repository instances bound to the current DB session. This keeps
  the service testable with mocked repos and transaction-safe (one session
  per request).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import selectinload

from core.exceptions import ConflictError, ForbiddenError, NotFoundError
from core.logging import get_logger
from domain.enums.permission import Permission
from domain.enums.role import Role
from models.membership import OrganizationMembership
from models.organization import Organization
from repositories.membership_repository import MembershipRepository
from repositories.organization_repository import OrganizationRepository
from repositories.user_repository import UserRepository
from security.rbac import require_permission
from utils.slugify import slugify

logger = get_logger(__name__)


class OrganizationService:
    def __init__(
        self,
        *,
        org_repo: OrganizationRepository,
        membership_repo: MembershipRepository,
        user_repo: UserRepository,
    ) -> None:
        self._orgs = org_repo
        self._memberships = membership_repo
        self._users = user_repo

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _require_membership(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> OrganizationMembership:
        """
        Load the user's membership, raising ForbiddenError if not a member.

        This is the entry point for every permission check. We intentionally
        return ForbiddenError (not NotFoundError) even when the org doesn't
        exist — this prevents org ID enumeration by non-members.
        """
        membership = await self._memberships.get_by_org_and_user(org_id, user_id)
        if not membership:
            raise ForbiddenError("You are not a member of this organization")
        return membership

    async def _require_permission(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        permission: Permission,
    ) -> OrganizationMembership:
        """Load membership and verify the user has the given permission."""
        membership = await self._require_membership(org_id, user_id)
        require_permission(Role(membership.role), permission)
        return membership

    async def _get_org_or_404(self, org_id: uuid.UUID) -> Organization:
        org = await self._orgs.get_by_id(org_id)
        if not org:
            raise NotFoundError("Organization not found")
        return org

    async def _owner_count(self, org_id: uuid.UUID) -> int:
        """Count members with OWNER role — used to prevent orphaning an org."""
        all_members = await self._memberships.list_by_org(org_id)
        return sum(1 for m in all_members if m.role == Role.OWNER.value)

    # ── Public API ────────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        name: str,
        slug: str | None,
        owner_user_id: uuid.UUID,
    ) -> Organization:
        """
        Create a new organization and add the creator as OWNER.

        Slug auto-generation: if slug is not provided, we derive it from the
        name. If the derived slug is taken, we raise ConflictError — the user
        should provide an explicit slug in that case.

        The owner membership is created in the same transaction. SQLAlchemy's
        unit-of-work ensures both rows are committed together.
        """
        resolved_slug = slug or slugify(name)
        if not resolved_slug:
            raise ConflictError("Cannot generate a valid slug from this name")

        if await self._orgs.slug_exists(resolved_slug):
            raise ConflictError(
                f"The slug '{resolved_slug}' is already taken. Please choose a different slug."
            )

        org = await self._orgs.create(name=name, slug=resolved_slug)

        await self._memberships.create(
            org_id=org.id,
            user_id=owner_user_id,
            role=Role.OWNER.value,
        )

        logger.info(
            "org.created",
            org_id=str(org.id),
            slug=org.slug,
            owner_id=str(owner_user_id),
        )
        return org

    async def get_by_slug(
        self,
        *,
        slug: str,
        requesting_user_id: uuid.UUID,
    ) -> Organization:
        """
        Return an org by slug, verifying the requester is a member.

        Returns ForbiddenError (not NotFoundError) when the org doesn't exist
        or the user isn't a member — prevents non-members from learning whether
        a given org slug is registered.
        """
        org = await self._orgs.get_by_slug(slug)
        if not org:
            raise ForbiddenError("Organization not found or access denied")

        await self._require_membership(org.id, requesting_user_id)
        return org

    async def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
    ) -> list[Organization]:
        """Return all orgs the user is a member of."""
        return await self._orgs.list_for_user(user_id)

    async def update(
        self,
        *,
        org_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        name: str | None = None,
    ) -> Organization:
        await self._require_permission(org_id, requesting_user_id, Permission.UPDATE_ORGANIZATION)
        org = await self._get_org_or_404(org_id)

        if name is not None:
            org.name = name

        await self._orgs.save(org)
        logger.info("org.updated", org_id=str(org_id))
        return org

    async def delete(
        self,
        *,
        org_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
    ) -> None:
        """
        Soft-delete an organization.

        Only the OWNER can delete an org (DELETE_ORGANIZATION permission).
        The soft delete sets deleted_at; the data remains in the DB for
        the retention period and can be restored if needed.
        """
        await self._require_permission(org_id, requesting_user_id, Permission.DELETE_ORGANIZATION)
        org = await self._get_org_or_404(org_id)
        await self._orgs.soft_delete(org)
        logger.info("org.deleted", org_id=str(org_id))

    async def list_members(
        self,
        *,
        org_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
    ) -> list[OrganizationMembership]:
        """
        Return all memberships with their user data pre-loaded.

        selectinload(OrganizationMembership.user) is passed as an option so the
        user's email and full_name are available without a second query per member.
        """
        await self._require_permission(org_id, requesting_user_id, Permission.VIEW_MEMBERS)
        return await self._memberships.list_by_org(
            org_id,
            options=[selectinload(OrganizationMembership.user)],
        )

    async def invite_member(
        self,
        *,
        org_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        email: str,
        role: str,
    ) -> OrganizationMembership:
        """
        Add an existing user to the organization.

        The invited user must already have a Hydra account. The role
        cannot be OWNER — ownership is transferred via transfer_ownership().

        Raises:
            ForbiddenError:  Requester lacks INVITE_MEMBER permission.
            NotFoundError:   Invited email has no Hydra account.
            ConflictError:   User is already a member.
        """
        await self._require_permission(org_id, requesting_user_id, Permission.INVITE_MEMBER)

        # The requester can't assign a role higher than their own.
        # (An ADMIN can't invite another ADMIN — only OWNER can.)
        requester_membership = await self._memberships.get_by_org_and_user(
            org_id, requesting_user_id
        )
        requester_role = Role(requester_membership.role)  # type: ignore[union-attr]
        target_role = Role(role)
        role_rank = {Role.VIEWER: 0, Role.MEMBER: 1, Role.ADMIN: 2, Role.OWNER: 3}
        if role_rank[target_role] >= role_rank[requester_role]:
            raise ForbiddenError(
                f"You cannot assign the '{role}' role — "
                "you can only invite members with a role lower than your own"
            )

        invited_user = await self._users.get_by_email(email)
        if not invited_user:
            raise NotFoundError(f"No account found for '{email}'")

        existing = await self._memberships.get_by_org_and_user(org_id, invited_user.id)
        if existing:
            raise ConflictError("This user is already a member of the organization")

        membership = await self._memberships.create(
            org_id=org_id,
            user_id=invited_user.id,
            role=role,
            invited_by_id=requesting_user_id,
        )
        # Mark joined_at immediately (no invite-acceptance flow yet)
        membership.joined_at = datetime.now(UTC)
        await self._memberships.save(membership)

        logger.info(
            "org.member_invited",
            org_id=str(org_id),
            invited_user_id=str(invited_user.id),
            role=role,
        )
        return membership

    async def remove_member(
        self,
        *,
        org_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        target_user_id: uuid.UUID,
    ) -> None:
        """
        Remove a member from the organization.

        Self-removal: any member can remove themselves.
        Removing others: requires REMOVE_MEMBER permission.
        Cannot remove the last OWNER.
        """
        is_self = requesting_user_id == target_user_id

        if not is_self:
            await self._require_permission(org_id, requesting_user_id, Permission.REMOVE_MEMBER)

        target = await self._memberships.get_by_org_and_user(org_id, target_user_id)
        if not target:
            raise NotFoundError("Member not found in this organization")

        if target.role == Role.OWNER.value:
            owner_count = await self._owner_count(org_id)
            if owner_count <= 1:
                raise ForbiddenError("Cannot remove the last owner. Transfer ownership first.")

        await self._memberships.delete(target)
        logger.info(
            "org.member_removed",
            org_id=str(org_id),
            removed_user_id=str(target_user_id),
        )

    async def update_member_role(
        self,
        *,
        org_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        target_user_id: uuid.UUID,
        new_role: str,
    ) -> OrganizationMembership:
        """
        Change a member's role.

        The requester must have UPDATE_MEMBER_ROLE permission.
        Cannot change a member's role to OWNER (use transfer_ownership).
        Cannot demote the last OWNER.
        """
        await self._require_permission(org_id, requesting_user_id, Permission.UPDATE_MEMBER_ROLE)

        target = await self._memberships.get_by_org_and_user(org_id, target_user_id)
        if not target:
            raise NotFoundError("Member not found in this organization")

        if target.role == Role.OWNER.value:
            owner_count = await self._owner_count(org_id)
            if owner_count <= 1:
                raise ForbiddenError(
                    "Cannot change the last owner's role. Transfer ownership first."
                )

        target.role = new_role
        await self._memberships.save(target)
        logger.info(
            "org.member_role_updated",
            org_id=str(org_id),
            target_user_id=str(target_user_id),
            new_role=new_role,
        )
        return target
