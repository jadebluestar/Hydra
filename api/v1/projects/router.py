from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.deps import get_current_user
from database.session import get_db
from models.user import User
from repositories.api_key_repository import APIKeyRepository
from repositories.membership_repository import MembershipRepository
from repositories.project_repository import ProjectRepository
from schemas.api_key import APIKeyCreatedResponse, APIKeyResponse, CreateAPIKeyRequest
from schemas.project import CreateProjectRequest, ProjectResponse, UpdateProjectRequest
from services.api_key_service import APIKeyService
from services.project_service import ProjectService

router = APIRouter(tags=["projects"])

CurrentUser = Annotated[User, Depends(get_current_user)]


def _project_service(session: AsyncSession) -> ProjectService:
    return ProjectService(
        project_repo=ProjectRepository(session),
        membership_repo=MembershipRepository(session),
    )


def _key_service(session: AsyncSession) -> APIKeyService:
    return APIKeyService(
        api_key_repo=APIKeyRepository(session),
        project_repo=ProjectRepository(session),
        membership_repo=MembershipRepository(session),
    )


# ── Project CRUD ──────────────────────────────────────────────────────────────


@router.get(
    "/organizations/{slug}/projects",
    response_model=list[ProjectResponse],
    tags=["organizations"],
    summary="List projects in an organization",
)
async def list_projects(
    slug: str,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectResponse]:
    from repositories.organization_repository import OrganizationRepository

    org = await OrganizationRepository(session).get_by_slug(slug)
    if not org:
        from core.exceptions import ForbiddenError

        raise ForbiddenError("Organization not found or access denied")
    svc = _project_service(session)
    projects = await svc.list_by_org(
        org_id=org.id,
        requesting_user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    return [ProjectResponse.model_validate(p) for p in projects]


@router.post(
    "/organizations/{slug}/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["organizations"],
    summary="Create a project in an organization",
)
async def create_project(
    slug: str,
    body: CreateProjectRequest,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    from repositories.organization_repository import OrganizationRepository

    org = await OrganizationRepository(session).get_by_slug(slug)
    if not org:
        from core.exceptions import ForbiddenError

        raise ForbiddenError("Organization not found or access denied")
    svc = _project_service(session)
    project = await svc.create(
        org_id=org.id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        requesting_user_id=current_user.id,
    )
    return ProjectResponse.model_validate(project)


@router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Get a project by ID",
)
async def get_project(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    svc = _project_service(session)
    project = await svc.get(project_id=project_id, requesting_user_id=current_user.id)
    return ProjectResponse.model_validate(project)


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Update a project",
)
async def update_project(
    project_id: uuid.UUID,
    body: UpdateProjectRequest,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    svc = _project_service(session)
    project = await svc.update(
        project_id=project_id,
        requesting_user_id=current_user.id,
        name=body.name,
        description=body.description,
    )
    return ProjectResponse.model_validate(project)


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
)
async def delete_project(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> None:
    svc = _project_service(session)
    await svc.delete(project_id=project_id, requesting_user_id=current_user.id)


# ── API Keys ──────────────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/api-keys",
    response_model=list[APIKeyResponse],
    summary="List API keys for a project",
)
async def list_api_keys(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
    include_revoked: bool = Query(default=False),
) -> list[APIKeyResponse]:
    svc = _key_service(session)
    keys = await svc.list(
        project_id=project_id,
        requesting_user_id=current_user.id,
        include_revoked=include_revoked,
    )
    return [APIKeyResponse.model_validate(k) for k in keys]


@router.post(
    "/projects/{project_id}/api-keys",
    response_model=APIKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an API key",
)
async def create_api_key(
    project_id: uuid.UUID,
    body: CreateAPIKeyRequest,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> APIKeyCreatedResponse:
    svc = _key_service(session)
    api_key, full_key = await svc.create(
        project_id=project_id,
        requesting_user_id=current_user.id,
        name=body.name,
        scopes=body.scopes,
        expires_at=body.expires_at,
    )
    base = APIKeyResponse.model_validate(api_key)
    return APIKeyCreatedResponse(**base.model_dump(), key=full_key)


@router.delete(
    "/projects/{project_id}/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
)
async def revoke_api_key(
    project_id: uuid.UUID,
    key_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> None:
    svc = _key_service(session)
    await svc.revoke(key_id=key_id, requesting_user_id=current_user.id)
