"""
Request playground — a Postman-like "try it" console for developers.

execute() runs the given request server-side using the same shared httpx
client the gateway proxy uses, so the browser UI never has to deal with CORS
when hitting third-party or internal upstreams. Requires an authenticated
platform user — this is a generic outbound HTTP proxy, so it must not be
exposed to anonymous callers.
"""

from __future__ import annotations

import time
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request

from api.v1.deps import get_current_user
from core.exceptions import ServiceUnavailableError
from models.user import User
from schemas.playground import PlaygroundRequest, PlaygroundResponse

router = APIRouter(prefix="/playground", tags=["playground"])

_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "transfer-encoding",
        "content-length",
        "content-encoding",
    }
)


@router.post(
    "/execute",
    response_model=PlaygroundResponse,
    summary="Execute an ad-hoc HTTP request and return the raw response",
)
async def execute(
    body: PlaygroundRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
) -> PlaygroundResponse:
    client: httpx.AsyncClient = request.app.state.gateway.http_client

    start_ns = time.monotonic_ns()
    try:
        upstream_resp = await client.request(
            method=body.method,
            url=str(body.url),
            params=body.query_params or None,
            headers=body.headers or None,
            content=body.body,
            timeout=float(body.timeout_seconds),
            follow_redirects=True,
        )
    except httpx.TimeoutException:
        raise ServiceUnavailableError("Request timed out")
    except httpx.ConnectError:
        raise ServiceUnavailableError("Could not connect to the target host")
    except httpx.RequestError as exc:
        raise ServiceUnavailableError(f"Request failed: {exc}")

    elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000

    response_headers = {
        k: v for k, v in upstream_resp.headers.items() if k.lower() not in _HOP_BY_HOP
    }

    return PlaygroundResponse(
        status_code=upstream_resp.status_code,
        headers=response_headers,
        body=upstream_resp.text,
        elapsed_ms=elapsed_ms,
        size_bytes=len(upstream_resp.content),
    )
