"""
Integration tests for health, readiness, and liveness endpoints.

test_health and test_live run without any infrastructure — they exercise
the full middleware stack but make no DB or Redis calls.

test_ready requires a running PostgreSQL and Redis. Mark it with
@pytest.mark.infra and run selectively:
    pytest -m "not infra"       # skip infra-dependent tests
    pytest -m infra             # run only infra-dependent tests
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_response_shape(client: AsyncClient) -> None:
    response = await client.get("/health")
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "environment" in body


@pytest.mark.asyncio
async def test_health_includes_request_id_header(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert "x-request-id" in response.headers


@pytest.mark.asyncio
async def test_health_propagates_request_id(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "my-trace-id"})
    assert response.headers["x-request-id"] == "my-trace-id"


@pytest.mark.asyncio
async def test_health_includes_correlation_id_header(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert "x-correlation-id" in response.headers


@pytest.mark.asyncio
async def test_live_returns_200(client: AsyncClient) -> None:
    response = await client.get("/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_unknown_route_returns_404(client: AsyncClient) -> None:
    response = await client.get("/does-not-exist")
    assert response.status_code == 404


@pytest.mark.infra
@pytest.mark.asyncio
async def test_ready_returns_200_when_infra_up(client: AsyncClient) -> None:
    """Requires PostgreSQL and Redis to be running."""
    response = await client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "ok"
