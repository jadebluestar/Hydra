from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AnalyticsSummary(BaseModel):
    total_requests: int
    success_count: int
    error_count: int
    rate_limited_count: int
    avg_latency_ms: float | None
    period_hours: int


class RequestLogEntry(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    api_key_id: uuid.UUID | None
    route_id: uuid.UUID | None
    http_method: str
    path: str
    status_code: int
    upstream_latency_ms: int | None
    total_latency_ms: int
    client_ip: str
    request_id: str
    is_rate_limited: bool
    created_at: datetime

    model_config = {"from_attributes": True}
