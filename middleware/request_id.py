"""
RequestID Middleware.

Assigns a unique identifier to every inbound request. If the caller supplies
an X-Request-ID header, we honor it (useful for tracing across services).
Otherwise we generate one.

The request_id is stored on request.state so downstream middleware and handlers
can read it without re-parsing headers.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or f"req_{uuid.uuid4().hex[:16]}"
        request.state.request_id = request_id

        response: Response = await call_next(request)  # type: ignore[operator]
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
