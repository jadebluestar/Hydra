from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.request_log import RequestLog
from repositories.base import BaseRepository


class RequestLogRepository(BaseRepository[RequestLog]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RequestLog)

    async def create(
        self,
        *,
        project_id: uuid.UUID | None,
        api_key_id: uuid.UUID | None,
        route_id: uuid.UUID | None,
        http_method: str,
        path: str,
        status_code: int,
        upstream_latency_ms: int | None,
        total_latency_ms: int,
        client_ip: str,
        request_id: str,
        is_rate_limited: bool,
    ) -> RequestLog:
        log = RequestLog(
            project_id=project_id,
            api_key_id=api_key_id,
            route_id=route_id,
            http_method=http_method,
            path=path,
            status_code=status_code,
            upstream_latency_ms=upstream_latency_ms,
            total_latency_ms=total_latency_ms,
            client_ip=client_ip,
            request_id=request_id,
            is_rate_limited=is_rate_limited,
        )
        return await self.save(log)

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RequestLog]:
        stmt = (
            select(RequestLog)
            .where(RequestLog.project_id == project_id)
            .order_by(RequestLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_summary(
        self,
        project_id: uuid.UUID,
        *,
        hours: int = 24,
    ) -> dict[str, Any]:
        """
        Aggregate request stats for a project over the last `hours` hours.

        Uses PostgreSQL's COUNT(1) FILTER (WHERE ...) to compute success/error
        counts in a single query rather than two separate SELECTs.
        """
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

        stmt = select(
            func.count(1).label("total"),
            func.count(1).filter(RequestLog.status_code < 400).label("success"),
            func.count(1).filter(RequestLog.is_rate_limited.is_(True)).label("rate_limited"),
            func.avg(cast(RequestLog.total_latency_ms, Integer)).label("avg_latency"),
        ).where(
            RequestLog.project_id == project_id,
            RequestLog.created_at >= since,
        )

        result = await self._session.execute(stmt)
        row = result.one()

        total = int(row.total or 0)
        success = int(row.success or 0)
        return {
            "total_requests": total,
            "success_count": success,
            "error_count": total - success,
            "rate_limited_count": int(row.rate_limited or 0),
            "avg_latency_ms": round(float(row.avg_latency), 2) if row.avg_latency else None,
            "period_hours": hours,
        }
