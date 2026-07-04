from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import HydraBase


class RequestLog(HydraBase):
    """
    Immutable record of a single gateway proxy request.

    Stored as a plain event log — no soft-delete, no FK constraints.
    IDs (project_id, api_key_id, route_id) are stored as soft references:
    logs outlive the entities they reference, so if a project is deleted
    its historical logs remain queryable.

    Written asynchronously as a BackgroundTask after the response is sent —
    log write latency never affects the client.
    """

    __tablename__ = "request_logs"

    # Identity — nullable because auth may fail before these are resolved
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    route_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Request
    http_method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    client_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # Response
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    # upstream_latency_ms is None when no upstream was reached (auth fail, no route, etc.)
    upstream_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    is_rate_limited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        # Primary query pattern: "requests for this project, newest first"
        Index("ix_request_logs_project_created", "project_id", "created_at"),
        # Secondary: "requests from this API key"
        Index("ix_request_logs_api_key_id", "api_key_id"),
    )
