from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.deps import get_current_user
from database.session import get_db
from models.user import User
from repositories.membership_repository import MembershipRepository
from repositories.organization_repository import OrganizationRepository
from repositories.user_repository import UserRepository
from schemas.organization import (
    CreateOrgRequest,
    InviteMemberRequest,
    MemberResponse,
    OrgResponse,
    UpdateMemberRoleRequest,
    UpdateOrgRequest,
)
from services.organization_service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["organizations"])

CurrentUser = Annotated[User, Depends(get_current_user)]


def _build_service(session: AsyncSession) -> OrganizationService:
    return OrganizationService(
        org_repo=OrganizationRepository(session),
        membership_repo=MembershipRepository(session),
        user_repo=UserRepository(session),
    )


@router.post(
    "",
    response_model=OrgResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization",
)
async def create_org(
    body: CreateOrgRequest,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> OrgResponse:
    svc = _build_service(session)
    org = await svc.create(
        name=body.name,
        slug=body.slug,
        owner_user_id=current_user.id,
    )
    return OrgResponse.model_validate(org)


@router.get(
    "",
    response_model=list[OrgResponse],
    summary="List organizations I belong to",
)
async def list_orgs(
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> list[OrgResponse]:
    svc = _build_service(session)
    orgs = await svc.list_for_user(user_id=current_user.id)
    return [OrgResponse.model_validate(o) for o in orgs]


@router.get(
    "/{slug}",
    response_model=OrgResponse,
    summary="Get an organization by slug",
)
async def get_org(
    slug: str,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> OrgResponse:
    svc = _build_service(session)
    org = await svc.get_by_slug(slug=slug, requesting_user_id=current_user.id)
    return OrgResponse.model_validate(org)


@router.patch(
    "/{slug}",
    response_model=OrgResponse,
    summary="Update organization details",
)
async def update_org(
    slug: str,
    body: UpdateOrgRequest,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> OrgResponse:
    svc = _build_service(session)
    # Resolve slug → org_id first
    org = await svc.get_by_slug(slug=slug, requesting_user_id=current_user.id)
    updated = await svc.update(
        org_id=org.id,
        requesting_user_id=current_user.id,
        name=body.name,
    )
    return OrgResponse.model_validate(updated)


@router.delete(
    "/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an organization (owner only)",
)
async def delete_org(
    slug: str,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> None:
    svc = _build_service(session)
    org = await svc.get_by_slug(slug=slug, requesting_user_id=current_user.id)
    await svc.delete(org_id=org.id, requesting_user_id=current_user.id)


@router.get(
    "/{slug}/members",
    response_model=list[MemberResponse],
    summary="List organization members",
)
async def list_members(
    slug: str,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> list[MemberResponse]:
    svc = _build_service(session)
    org = await svc.get_by_slug(slug=slug, requesting_user_id=current_user.id)
    members = await svc.list_members(
        org_id=org.id, requesting_user_id=current_user.id
    )
    return [
        MemberResponse(
            user_id=m.user_id,
            email=m.user.email,
            full_name=m.user.full_name,
            role=m.role,
            joined_at=m.joined_at,
            member_since=m.created_at,
        )
        for m in members
    ]


@router.post(
    "/{slug}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a user to the organization",
)
async def invite_member(
    slug: str,
    body: InviteMemberRequest,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> MemberResponse:
    svc = _build_service(session)
    org = await svc.get_by_slug(slug=slug, requesting_user_id=current_user.id)
    membership = await svc.invite_member(
        org_id=org.id,
        requesting_user_id=current_user.id,
        email=str(body.email),
        role=body.role,
    )
    # Reload with user data for the response
    from sqlalchemy.orm import selectinload
    from repositories.membership_repository import MembershipRepository as MR
    m = await MR(session).get_by_org_and_user(
        org.id,
        membership.user_id,
        options=[selectinload(type(membership).user)],
    )
    return MemberResponse(
        user_id=m.user_id,  # type: ignore[union-attr]
        email=m.user.email,  # type: ignore[union-attr]
        full_name=m.user.full_name,  # type: ignore[union-attr]
        role=m.role,  # type: ignore[union-attr]
        joined_at=m.joined_at,  # type: ignore[union-attr]
        member_since=m.created_at,  # type: ignore[union-attr]
    )


@router.patch(
    "/{slug}/members/{user_id}",
    response_model=MemberResponse,
    summary="Update a member's role",
)
async def update_member_role(
    slug: str,
    user_id: uuid.UUID,
    body: UpdateMemberRoleRequest,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> MemberResponse:
    svc = _build_service(session)
    org = await svc.get_by_slug(slug=slug, requesting_user_id=current_user.id)
    from sqlalchemy.orm import selectinload
    from models.membership import OrganizationMembership
    membership = await svc.update_member_role(
        org_id=org.id,
        requesting_user_id=current_user.id,
        target_user_id=user_id,
        new_role=body.role,
    )
    m = await MembershipRepository(session).get_by_org_and_user(
        org.id,
        user_id,
        options=[selectinload(OrganizationMembership.user)],
    )
    return MemberResponse(
        user_id=m.user_id,  # type: ignore[union-attr]
        email=m.user.email,  # type: ignore[union-attr]
        full_name=m.user.full_name,  # type: ignore[union-attr]
        role=m.role,  # type: ignore[union-attr]
        joined_at=m.joined_at,  # type: ignore[union-attr]
        member_since=m.created_at,  # type: ignore[union-attr]
    )


@router.delete(
    "/{slug}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from the organization",
)
async def remove_member(
    slug: str,
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> None:
    svc = _build_service(session)
    org = await svc.get_by_slug(slug=slug, requesting_user_id=current_user.id)
    await svc.remove_member(
        org_id=org.id,
        requesting_user_id=current_user.id,
        target_user_id=user_id,
    )
