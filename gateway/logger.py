"""
Gateway request logger.

write_request_log() is called as a FastAPI BackgroundTask after the response
is sent to the client. It creates a fresh database session from the pool so
that the request-scoped session (already committed and closed) is not reused.

Errors during log writes are caught and logged with structlog rather than
re-raised — a failed analytics write must never affect the client.
"""

from __future__ import annotations

import uuid

import structlog

from database.session import get_standalone_session
from repositories.request_log_repository import RequestLogRepository

logger = structlog.get_logger(__name__)


async def write_request_log(
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
) -> None:
    try:
        async with get_standalone_session() as session:
            await RequestLogRepository(session).create(
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
    except Exception:
        logger.error(
            "gateway.request_log_failed",
            exc_info=True,
            path=path,
            status_code=status_code,
        )
