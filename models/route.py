from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import HydraSoftDeleteBase

if TYPE_CHECKING:
    from models.project import Project
    from models.upstream import Upstream


class Route(HydraSoftDeleteBase):
    """
    A route maps an inbound path prefix to an upstream backend.

    This is the gateway's core primitive. Every inbound request goes
    through the trie matcher (Milestone 13) which finds the best matching
    route by path_prefix.

    Example route:
      path_prefix:    "/api/v1/users"
      methods:        ["GET", "POST"]
      upstream:       user-service (http://user-svc:8080)
      required_scope: "gateway:read"
      strip_prefix:   True   → forwards as "/users/..."
      strip_prefix:   False  → forwards as "/api/v1/users/..."

    Why path_prefix + trie instead of exact match + SQL?
      Exact SQL lookups need a query per request. The trie is loaded
      into memory at startup and updated on route changes — lookups
      are O(k) where k is the path length, with zero DB round-trips
      on the hot path. This is why Kong, Nginx, and Envoy use trie
      routing internally.
    """

    __tablename__ = "routes"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    upstream_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("upstreams.id", ondelete="RESTRICT"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # The path prefix this route matches. Must start with '/'.
    # The trie is built from these values at startup.
    path_prefix: Mapped[str] = mapped_column(String(2048), nullable=False)

    # HTTP methods this route accepts. Empty list [] = all methods.
    # Stored as JSONB: ["GET", "POST"] or []
    methods: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )

    # The APIKeyScope string value required to access this route.
    # None = route is public (no auth required).
    required_scope: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # If True, strip path_prefix before forwarding.
    # Route /api/v1 → upstream, request /api/v1/users/123:
    #   strip_prefix=True  → upstream receives /users/123
    #   strip_prefix=False → upstream receives /api/v1/users/123
    strip_prefix: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Requests per minute limit for this route. None = unlimited.
    # Per API key if a key is present, per IP otherwise.
    rate_limit_rpm: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Disabled routes are not loaded into the trie — effectively invisible
    # to the gateway without deleting the config.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    project: Mapped[Project] = relationship(
        "Project",
        back_populates="routes",
        lazy="raise",
    )
    upstream: Mapped[Upstream] = relationship(
        "Upstream",
        back_populates="routes",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_routes_project_id", "project_id"),
        # Index on path_prefix for the admin API (searching, filtering routes).
        # The gateway itself uses the in-memory trie, not this index.
        Index("ix_routes_path_prefix", "path_prefix"),
        Index("ix_routes_upstream_id", "upstream_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Route id={self.id} path={self.path_prefix!r} "
            f"active={self.is_active}>"
        )
