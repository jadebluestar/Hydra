from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import HydraSoftDeleteBase

if TYPE_CHECKING:
    from models.project import Project
    from models.route import Route


class Upstream(HydraSoftDeleteBase):
    """
    An upstream is a backend service that routes proxy traffic to.

    Separating upstreams from routes allows multiple routes to share
    one upstream. Example:
      - Route: /api/v1/users  → Upstream: user-service (http://user-svc:8080)
      - Route: /api/v1/profile → Upstream: user-service (same upstream)

    This is the same mental model as Kong's upstreams and Nginx's upstreams.

    Future: upstreams can have multiple targets with load-balancing weights
    (Milestone 15 — load balancer). For now, one base_url per upstream.
    """

    __tablename__ = "upstreams"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # The base URL of the backend service, without trailing slash.
    # Example: "http://user-service:8080" or "https://api.partner.com"
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)

    # Per-request timeout in seconds. Overrides the global default.
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    # How many times to retry a failed request before returning 502.
    # Only safe for idempotent methods (GET, HEAD, PUT). The gateway
    # checks the method before retrying (Milestone 14).
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    project: Mapped[Project] = relationship(
        "Project",
        back_populates="upstreams",
        lazy="raise",
    )
    routes: Mapped[list[Route]] = relationship(
        "Route",
        back_populates="upstream",
        lazy="raise",
    )

    __table_args__ = (Index("ix_upstreams_project_id", "project_id"),)

    def __repr__(self) -> str:
        return f"<Upstream id={self.id} name={self.name!r} url={self.base_url!r}>"
