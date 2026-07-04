"""
Logging Middleware.

Emits two structured log events per request:
  - request.started   — method, path, client IP
  - request.completed — adds status code and duration in milliseconds

Request context (request_id, correlation_id) is bound into structlog's
context variable store, which means every log line produced anywhere in the
async call stack — services, repositories, background tasks — automatically
includes these fields without being explicitly passed around.

This works because structlog.contextvars uses Python's contextvars module,
which is copy-on-write per asyncio Task. Concurrent requests never bleed
context into each other.
"""

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        start = time.perf_counter()

        # Clear any context leftover from a pooled connection/worker,
        # then bind this request's identifiers for all downstream log calls.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=getattr(request.state, "request_id", None),
            correlation_id=getattr(request.state, "correlation_id", None),
            method=request.method,
            path=str(request.url.path),
            client_ip=request.client.host if request.client else None,
        )

        logger.info("request.started")

        response: Response = await call_next(request)  # type: ignore[operator]

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "request.completed",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        structlog.contextvars.clear_contextvars()
        return response
