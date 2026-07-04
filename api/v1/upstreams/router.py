from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.deps import get_current_user
from database.session import get_db
from gateway.state import GatewayState
from models.user import User
from repositories.membership_repository import MembershipRepository
from repositories.project_repository import ProjectRepository
from repositories.upstream_repository import UpstreamRepository
from schemas.upstream import CreateUpstreamRequest, UpdateUpstreamRequest, UpstreamResponse
from services.upstream_service import UpstreamService

router = APIRouter(tags=["upstreams"])

CurrentUser = Annotated[User, Depends(get_current_user)]


def _invalidate(request: Request, project_id: uuid.UUID) -> None:
    gateway: GatewayState = request.app.state.gateway
    gateway.invalidate(project_id)


def _svc(session: AsyncSession) -> UpstreamService:
    return UpstreamService(
        upstream_repo=UpstreamRepository(session),
        project_repo=ProjectRepository(session),
        membership_repo=MembershipRepository(session),
    )


@router.get(
    "/projects/{project_id}/upstreams",
    response_model=list[UpstreamResponse],
    summary="List upstreams for a project",
)
async def list_upstreams(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[UpstreamResponse]:
    svc = _svc(session)
    upstreams = await svc.list(
        project_id=project_id,
        requesting_user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    return [UpstreamResponse.model_validate(u) for u in upstreams]


@router.post(
    "/projects/{project_id}/upstreams",
    response_model=UpstreamResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an upstream",
)
async def create_upstream(
    project_id: uuid.UUID,
    body: CreateUpstreamRequest,
    request: Request,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> UpstreamResponse:
    svc = _svc(session)
    upstream = await svc.create(
        project_id=project_id,
        requesting_user_id=current_user.id,
        name=body.name,
        base_url=body.base_url,
        timeout_seconds=body.timeout_seconds,
        retries=body.retries,
    )
    _invalidate(request, project_id)
    return UpstreamResponse.model_validate(upstream)


@router.get(
    "/projects/{project_id}/upstreams/{upstream_id}",
    response_model=UpstreamResponse,
    summary="Get an upstream by ID",
)
async def get_upstream(
    project_id: uuid.UUID,
    upstream_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> UpstreamResponse:
    svc = _svc(session)
    upstream = await svc.get(
        upstream_id=upstream_id,
        project_id=project_id,
        requesting_user_id=current_user.id,
    )
    return UpstreamResponse.model_validate(upstream)


@router.patch(
    "/projects/{project_id}/upstreams/{upstream_id}",
    response_model=UpstreamResponse,
    summary="Update an upstream",
)
async def update_upstream(
    project_id: uuid.UUID,
    upstream_id: uuid.UUID,
    body: UpdateUpstreamRequest,
    request: Request,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> UpstreamResponse:
    svc = _svc(session)
    upstream = await svc.update(
        upstream_id=upstream_id,
        project_id=project_id,
        requesting_user_id=current_user.id,
        **body.model_dump(exclude_unset=True),
    )
    _invalidate(request, project_id)
    return UpstreamResponse.model_validate(upstream)


@router.delete(
    "/projects/{project_id}/upstreams/{upstream_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an upstream",
)
async def delete_upstream(
    project_id: uuid.UUID,
    upstream_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> None:
    svc = _svc(session)
    await svc.delete(
        upstream_id=upstream_id,
        project_id=project_id,
        requesting_user_id=current_user.id,
    )
    _invalidate(request, project_id)
