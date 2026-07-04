"""
CorrelationID Middleware.

The Correlation ID ties together a chain of requests that are logically related —
for example, a browser request that triggers three downstream service calls. The
first service in the chain generates it; every downstream hop passes it along.

If the caller includes X-Correlation-ID, we propagate it unchanged.
If not, we generate a new one — this request is the origin of a new trace chain.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_ID_HEADER = "X-Correlation-ID"


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        correlation_id = (
            request.headers.get(CORRELATION_ID_HEADER) or f"corr_{uuid.uuid4().hex[:16]}"
        )
        request.state.correlation_id = correlation_id

        response: Response = await call_next(request)  # type: ignore[operator]
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
