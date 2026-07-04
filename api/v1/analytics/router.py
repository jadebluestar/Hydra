from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.deps import get_current_user
from database.session import get_db
from models.user import User
from repositories.membership_repository import MembershipRepository
from repositories.project_repository import ProjectRepository
from repositories.request_log_repository import RequestLogRepository
from schemas.analytics import AnalyticsSummary, RequestLogEntry
from services.analytics_service import AnalyticsService

router = APIRouter(tags=["analytics"])

CurrentUser = Annotated[User, Depends(get_current_user)]


def _svc(session: AsyncSession) -> AnalyticsService:
    return AnalyticsService(
        log_repo=RequestLogRepository(session),
        project_repo=ProjectRepository(session),
        membership_repo=MembershipRepository(session),
    )


@router.get(
    "/projects/{project_id}/analytics/summary",
    response_model=AnalyticsSummary,
    summary="Gateway traffic summary for a project",
)
async def get_analytics_summary(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
    hours: int = Query(default=24, ge=1, le=720),
) -> AnalyticsSummary:
    svc = _svc(session)
    data = await svc.get_summary(
        project_id=project_id,
        requesting_user_id=current_user.id,
        hours=hours,
    )
    return AnalyticsSummary(**data)


@router.get(
    "/projects/{project_id}/analytics/requests",
    response_model=list[RequestLogEntry],
    summary="Paginated gateway request log for a project",
)
async def list_request_logs(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[RequestLogEntry]:
    svc = _svc(session)
    logs = await svc.list_requests(
        project_id=project_id,
        requesting_user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    return [RequestLogEntry.model_validate(log) for log in logs]
