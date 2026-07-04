"""Unit tests for the gateway forward_request() function."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException

from gateway.proxy import forward_request


def _mock_response(
    status_code: int = 200,
    content: bytes = b'{"ok": true}',
    headers: dict[str, str] | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.status_code = status_code
    resp.headers = headers or {"content-type": "application/json"}
    return resp


def _mock_client(response: MagicMock) -> AsyncMock:
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request.return_value = response
    return client


class TestForwardRequestSuccess:
    async def test_returns_upstream_status_code(self) -> None:
        client = _mock_client(_mock_response(status_code=201))
        resp = await forward_request(
            client=client,
            method="POST",
            url="http://upstream:8080/users",
            headers={},
            body=b'{"name": "Alice"}',
            timeout=30,
            client_ip="1.2.3.4",
        )
        assert resp.status_code == 201

    async def test_returns_upstream_body(self) -> None:
        client = _mock_client(_mock_response(content=b"hello"))
        resp = await forward_request(
            client=client,
            method="GET",
            url="http://upstream:8080/",
            headers={},
            body=b"",
            timeout=30,
            client_ip="1.2.3.4",
        )
        assert resp.body == b"hello"

    async def test_passes_method_and_url(self) -> None:
        client = _mock_client(_mock_response())
        await forward_request(
            client=client,
            method="DELETE",
            url="http://upstream:8080/users/123",
            headers={},
            body=b"",
            timeout=30,
            client_ip="1.2.3.4",
        )
        call_kwargs = client.request.call_args.kwargs
        assert call_kwargs["method"] == "DELETE"
        assert call_kwargs["url"] == "http://upstream:8080/users/123"


class TestForwardRequestHeaders:
    async def test_hop_by_hop_headers_stripped_from_request(self) -> None:
        client = _mock_client(_mock_response())
        await forward_request(
            client=client,
            method="GET",
            url="http://upstream:8080/",
            headers={
                "accept": "application/json",
                "connection": "keep-alive",
                "transfer-encoding": "chunked",
                "content-length": "0",
                "te": "trailers",
            },
            body=b"",
            timeout=30,
            client_ip="1.2.3.4",
        )
        sent = client.request.call_args.kwargs["headers"]
        assert "connection" not in sent
        assert "transfer-encoding" not in sent
        assert "content-length" not in sent
        assert "te" not in sent
        assert "accept" in sent  # non-hop-by-hop: kept

    async def test_x_forwarded_for_added(self) -> None:
        client = _mock_client(_mock_response())
        await forward_request(
            client=client,
            method="GET",
            url="http://upstream:8080/",
            headers={"host": "hydra.example.com"},
            body=b"",
            timeout=30,
            client_ip="10.0.0.1",
        )
        sent = client.request.call_args.kwargs["headers"]
        assert sent["x-forwarded-for"] == "10.0.0.1"
        assert sent["x-forwarded-host"] == "hydra.example.com"

    async def test_hop_by_hop_headers_stripped_from_response(self) -> None:
        response = _mock_response(
            headers={
                "content-type": "application/json",
                "transfer-encoding": "chunked",  # should be stripped
                "x-custom-header": "kept",
            }
        )
        client = _mock_client(response)
        resp = await forward_request(
            client=client,
            method="GET",
            url="http://upstream:8080/",
            headers={},
            body=b"",
            timeout=30,
            client_ip="1.2.3.4",
        )
        raw_headers = dict(resp.headers)
        assert "transfer-encoding" not in raw_headers
        assert "x-custom-header" in raw_headers


class TestForwardRequestErrors:
    async def test_timeout_raises_504(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request.side_effect = httpx.TimeoutException("timed out")
        with pytest.raises(HTTPException) as exc:
            await forward_request(
                client=client,
                method="GET",
                url="http://slow-upstream:8080/",
                headers={},
                body=b"",
                timeout=1,
                client_ip="1.2.3.4",
            )
        assert exc.value.status_code == 504

    async def test_connect_error_raises_502(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request.side_effect = httpx.ConnectError("connection refused")
        with pytest.raises(HTTPException) as exc:
            await forward_request(
                client=client,
                method="GET",
                url="http://unreachable:8080/",
                headers={},
                body=b"",
                timeout=5,
                client_ip="1.2.3.4",
            )
        assert exc.value.status_code == 502

    async def test_generic_request_error_raises_502(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request.side_effect = httpx.RequestError("generic error")
        with pytest.raises(HTTPException) as exc:
            await forward_request(
                client=client,
                method="GET",
                url="http://broken:8080/",
                headers={},
                body=b"",
                timeout=5,
                client_ip="1.2.3.4",
            )
        assert exc.value.status_code == 502
