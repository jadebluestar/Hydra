"""
Gateway proxy endpoint.

A single catch-all route handles all methods and paths under /gateway/.
The gateway URL space is separate from the management API (/api/v1/):

    Management plane:  POST /api/v1/organizations   (admin, JWT-authenticated)
    Data plane:        POST /gateway/api/orders      (API key-authenticated)

Per-request flow:
  1.  Extract API key from Authorization: Bearer header
  2.  Verify key via SHA-256 hash → resolve project_id and scopes
  3.  Load project's PathTrie (lazy-load from DB on first hit, then cached)
  4.  Longest-prefix match on the request path
  5.  Scope check (key scopes vs route required_scope)
  6.  Method check (route methods allow-list, if non-empty)
  7.  Rate limit check (sliding window, per API key per route)
  8.  Circuit breaker check (return 503 immediately if upstream is OPEN)
  9.  Strip path prefix if route.strip_prefix = True
  10. Forward to upstream via shared httpx.AsyncClient;
      record circuit breaker success or failure
  11. Return upstream's response
  12. (Background) Write request log to Postgres
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from cache.client import get_redis
from core.exceptions import HydraError, UnauthorizedError
from database.session import get_db
from domain.enums.circuit_state import CircuitState
from gateway.auth import check_scope, extract_api_key
from gateway.circuit_breaker import UPSTREAM_ERROR_CODES, CircuitBreaker
from gateway.logger import write_request_log
from gateway.proxy import forward_request
from gateway.rate_limiter import check_rate_limit
from gateway.state import GatewayState
from gateway.trie import RouteMatch
from repositories.api_key_repository import APIKeyRepository
from repositories.membership_repository import MembershipRepository
from repositories.project_repository import ProjectRepository
from repositories.route_repository import RouteRepository
from services.api_key_service import APIKeyService

router = APIRouter(tags=["gateway"])


def _key_service(session: AsyncSession) -> APIKeyService:
    return APIKeyService(
        api_key_repo=APIKeyRepository(session),
        project_repo=ProjectRepository(session),
        membership_repo=MembershipRepository(session),
    )


async def _build_route_matches(
    route_repo: RouteRepository,
    project_id: uuid.UUID,
) -> list[RouteMatch]:
    """
    Load active routes + upstreams for a project and convert to RouteMatch dataclasses.

    Runs inside the GatewayState.get_trie() loader callback — only called when
    the project's trie is not yet cached. Route.upstream is eagerly loaded by
    list_active_with_upstream() via selectinload, so route.upstream is safe here.
    """
    routes = await route_repo.list_active_with_upstream(project_id)
    return [
        RouteMatch(
            route_id=r.id,
            path_prefix=r.path_prefix,
            upstream_base_url=r.upstream.base_url,
            upstream_timeout_seconds=r.upstream.timeout_seconds,
            upstream_retries=r.upstream.retries,
            methods=r.methods,
            required_scope=r.required_scope,
            strip_prefix=r.strip_prefix,
            rate_limit_rpm=r.rate_limit_rpm,
            is_active=r.is_active,
            upstream_id=r.upstream_id,
        )
        for r in routes
    ]


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def gateway_proxy(
    path: str,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),  # type: ignore[type-arg]
) -> Response:
    start_ns = time.monotonic_ns()

    # Mutable log context — populated as each step resolves
    log_project_id: uuid.UUID | None = None
    log_api_key_id: uuid.UUID | None = None
    log_route_id: uuid.UUID | None = None
    log_status_code = 500
    log_upstream_ms: int | None = None
    log_is_rate_limited = False
    full_path = f"/{path}" if path else "/"
    client_ip = request.client.host if request.client else "unknown"
    request_id = request.headers.get("x-request-id", "")

    # Tracks circuit breaker state so record_success/record_failure know which
    # transition to make. Initialized here (outside try) so the inner except
    # block can always reference it without an UnboundLocalError.
    cb_state: CircuitState = CircuitState.CLOSED

    try:
        # 1. Extract and verify API key
        raw_key = extract_api_key(request)

        key_svc = _key_service(session)
        api_key = await key_svc.verify(raw_key)
        if api_key is None:
            raise UnauthorizedError("Invalid or revoked API key")

        log_api_key_id = api_key.id
        log_project_id = api_key.project_id

        # 2. Load (or retrieve cached) route trie for this project
        gateway: GatewayState = request.app.state.gateway
        route_repo = RouteRepository(session)
        project_id = api_key.project_id

        trie = await gateway.get_trie(
            project_id,
            loader=lambda: _build_route_matches(route_repo, project_id),
        )

        # 3. Match path prefix — longest prefix wins
        match = trie.match(full_path)
        if match is None:
            raise HTTPException(status_code=404, detail="No route matches this path")

        log_route_id = match.route_id

        # 4. Scope check — 403 if key lacks required scope
        check_scope(api_key.scopes, match.required_scope)

        # 5. Method check
        if match.methods and request.method not in match.methods:
            raise HTTPException(
                status_code=405,
                detail=f"Method {request.method} not allowed on this route",
                headers={"Allow": ", ".join(match.methods)},
            )

        # 6. Rate limit check — sliding window, per API key per route
        if match.rate_limit_rpm is not None:
            try:
                await check_rate_limit(
                    redis,
                    api_key_id=str(api_key.id),
                    route_id=str(match.route_id),
                    limit=match.rate_limit_rpm,
                )
            except HydraError:
                log_is_rate_limited = True
                raise

        # 7. Circuit breaker — reject immediately if upstream is known-down.
        # Raises ServiceUnavailableError (503) when OPEN; sets cb_state to
        # HALF_OPEN when the recovery timeout has passed and this request
        # claims the probe slot; returns CLOSED otherwise.
        cb = CircuitBreaker(redis)
        cb_state = await cb.check(str(match.upstream_id))

        # 8. Build target URL — strip prefix if configured
        target_path = full_path
        if match.strip_prefix and match.path_prefix != "/":
            target_path = full_path[len(match.path_prefix):] or "/"

        url = match.upstream_base_url + target_path

        # 9. Forward — record circuit breaker outcome and upstream latency.
        # Inner try/except separates CB recording from the outer error handler
        # so that upstream errors can update the breaker before the outer
        # except sets log_status_code and re-raises.
        upstream_start_ns = time.monotonic_ns()
        try:
            response = await forward_request(
                client=gateway.http_client,
                method=request.method,
                url=url,
                headers=dict(request.headers),
                body=await request.body(),
                timeout=match.upstream_timeout_seconds,
                client_ip=client_ip,
            )
            log_upstream_ms = (time.monotonic_ns() - upstream_start_ns) // 1_000_000
            was_half_open = cb_state == CircuitState.HALF_OPEN
            if response.status_code in UPSTREAM_ERROR_CODES:
                await cb.record_failure(str(match.upstream_id), was_half_open=was_half_open)
            else:
                await cb.record_success(str(match.upstream_id), was_half_open=was_half_open)
        except HTTPException as upstream_exc:
            # forward_request raises HTTPException for 502 (connect error) and
            # 504 (timeout) — both count as upstream failures for the breaker.
            if upstream_exc.status_code in UPSTREAM_ERROR_CODES:
                await cb.record_failure(
                    str(match.upstream_id),
                    was_half_open=(cb_state == CircuitState.HALF_OPEN),
                )
            raise

        log_status_code = response.status_code
        return response

    except HydraError as exc:
        log_status_code = exc.status_code
        raise
    except HTTPException as exc:
        log_status_code = exc.status_code
        raise

    finally:
        total_ms = (time.monotonic_ns() - start_ns) // 1_000_000
        background_tasks.add_task(
            write_request_log,
            project_id=log_project_id,
            api_key_id=log_api_key_id,
            route_id=log_route_id,
            http_method=request.method,
            path=full_path,
            status_code=log_status_code,
            upstream_latency_ms=log_upstream_ms,
            total_latency_ms=total_ms,
            client_ip=client_ip,
            request_id=request_id,
            is_rate_limited=log_is_rate_limited,
        )
