"""
Health, Readiness, and Liveness endpoints.

These three endpoints serve different purposes and different consumers:

  GET /health
    Basic liveness check. Returns 200 as long as the Python process is running
    and can handle HTTP requests. No external dependencies checked.
    Used by: developers, monitoring dashboards.

  GET /ready
    Readiness check. Verifies that ALL required dependencies (database, Redis)
    are reachable before the application is considered ready to serve traffic.
    Returns 503 if any check fails so load balancers can stop sending traffic
    to an unhealthy instance.
    Used by: Kubernetes readiness probes, load balancers.

  GET /live
    Liveness check. Minimal signal — "is this process still alive?"
    Used by: Kubernetes liveness probes (triggers a pod restart if this fails).

Interview note: readiness ≠ liveness. A pod that is temporarily overloaded
should fail readiness (stop receiving new traffic) but NOT liveness (do not
restart it — the problem is load, not a hung process).
"""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cache.client import get_redis
from core.config import get_settings
from database.session import get_db
from redis.asyncio import Redis
from schemas.common import HealthResponse, LivenessResponse, ReadinessCheck

router = APIRouter(tags=["observability"])
settings = get_settings()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Application health",
)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
    )


@router.get(
    "/ready",
    summary="Application readiness",
    responses={
        200: {"description": "All dependencies reachable"},
        503: {"description": "One or more dependencies unavailable"},
    },
)
async def ready(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> JSONResponse:
    checks: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"

    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"

    all_ok = all(v == "ok" for v in checks.values())

    return JSONResponse(
        content=ReadinessCheck(
            status="ready" if all_ok else "degraded",
            checks=checks,
        ).model_dump(),
        status_code=status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Kubernetes liveness probe",
)
async def live() -> LivenessResponse:
    return LivenessResponse(status="alive")
