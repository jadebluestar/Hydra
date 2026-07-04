"""
HTTP request forwarding logic.

forward_request() takes a fully-resolved upstream URL and proxies the
inbound request to it, returning a FastAPI Response with the upstream's
status, headers, and body.

Header policy (RFC 7230 §6.1):
  - Drop hop-by-hop headers — they're transport-layer concerns that must
    not be forwarded through a proxy (Connection, Transfer-Encoding, etc.)
  - Add X-Forwarded-* so upstreams can reconstruct the original request context.
  - Pass everything else through untouched.

Error mapping:
  - Upstream timeout  → 504 Gateway Timeout
  - Upstream connection failure → 502 Bad Gateway
"""

from __future__ import annotations

import httpx
from fastapi import HTTPException
from fastapi.responses import Response

_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-length",  # httpx sets this from body content automatically
    }
)


async def forward_request(
    *,
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes,
    timeout: int,
    client_ip: str,
) -> Response:
    forward_headers = {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP}
    forward_headers["x-forwarded-for"] = client_ip
    forward_headers["x-forwarded-host"] = headers.get("host", "")
    forward_headers["x-forwarded-proto"] = "https"

    try:
        upstream_resp = await client.request(
            method=method,
            url=url,
            headers=forward_headers,
            content=body,
            timeout=float(timeout),
            follow_redirects=False,
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream timed out")
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Upstream connection failed")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream request failed: {exc}")

    response_headers = {
        k: v for k, v in upstream_resp.headers.items() if k.lower() not in _HOP_BY_HOP
    }

    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers=response_headers,
    )
