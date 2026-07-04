from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.deps import get_current_user
from database.session import get_db
from gateway.state import GatewayState
from models.user import User
from repositories.membership_repository import MembershipRepository
from repositories.project_repository import ProjectRepository
from repositories.route_repository import RouteRepository
from repositories.upstream_repository import UpstreamRepository
from schemas.route import CreateRouteRequest, RouteResponse, UpdateRouteRequest
from services.route_service import RouteService

router = APIRouter(tags=["routes"])

CurrentUser = Annotated[User, Depends(get_current_user)]


def _invalidate(request: Request, project_id: uuid.UUID) -> None:
    gateway: GatewayState = request.app.state.gateway
    gateway.invalidate(project_id)


def _svc(session: AsyncSession) -> RouteService:
    return RouteService(
        route_repo=RouteRepository(session),
        upstream_repo=UpstreamRepository(session),
        project_repo=ProjectRepository(session),
        membership_repo=MembershipRepository(session),
    )


@router.get(
    "/projects/{project_id}/routes",
    response_model=list[RouteResponse],
    summary="List routes for a project",
)
async def list_routes(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
    active_only: bool = Query(default=True),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[RouteResponse]:
    svc = _svc(session)
    routes = await svc.list(
        project_id=project_id,
        requesting_user_id=current_user.id,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return [RouteResponse.model_validate(r) for r in routes]


@router.post(
    "/projects/{project_id}/routes",
    response_model=RouteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a route",
)
async def create_route(
    project_id: uuid.UUID,
    body: CreateRouteRequest,
    request: Request,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> RouteResponse:
    svc = _svc(session)
    route = await svc.create(
        project_id=project_id,
        requesting_user_id=current_user.id,
        name=body.name,
        path_prefix=body.path_prefix,
        upstream_id=body.upstream_id,
        methods=body.methods,
        required_scope=body.required_scope,
        strip_prefix=body.strip_prefix,
        rate_limit_rpm=body.rate_limit_rpm,
        is_active=body.is_active,
    )
    _invalidate(request, project_id)
    return RouteResponse.model_validate(route)


@router.get(
    "/projects/{project_id}/routes/{route_id}",
    response_model=RouteResponse,
    summary="Get a route by ID",
)
async def get_route(
    project_id: uuid.UUID,
    route_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> RouteResponse:
    svc = _svc(session)
    route = await svc.get(
        route_id=route_id,
        project_id=project_id,
        requesting_user_id=current_user.id,
    )
    return RouteResponse.model_validate(route)


@router.patch(
    "/projects/{project_id}/routes/{route_id}",
    response_model=RouteResponse,
    summary="Update a route",
)
async def update_route(
    project_id: uuid.UUID,
    route_id: uuid.UUID,
    body: UpdateRouteRequest,
    request: Request,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> RouteResponse:
    svc = _svc(session)
    # exclude_unset=True ensures fields absent from the request body are not
    # forwarded to the service — this lets the service distinguish "don't change"
    # from "explicitly set to null" for nullable fields like required_scope.
    updates: dict[str, Any] = body.model_dump(exclude_unset=True)
    route = await svc.update(
        route_id=route_id,
        project_id=project_id,
        requesting_user_id=current_user.id,
        **updates,
    )
    _invalidate(request, project_id)
    return RouteResponse.model_validate(route)


@router.delete(
    "/projects/{project_id}/routes/{route_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a route",
)
async def delete_route(
    project_id: uuid.UUID,
    route_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> None:
    svc = _svc(session)
    await svc.delete(
        route_id=route_id,
        project_id=project_id,
        requesting_user_id=current_user.id,
    )
    _invalidate(request, project_id)
