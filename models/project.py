from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import HydraSoftDeleteBase

if TYPE_CHECKING:
    from models.api_key import APIKey
    from models.organization import Organization
    from models.route import Route
    from models.upstream import Upstream


class Project(HydraSoftDeleteBase):
    """
    A project groups routes, upstreams, and API keys for one product or team.

    Every gateway configuration belongs to exactly one project. A user/org
    can have many projects (e.g., "production", "staging", "mobile-api").

    The project slug is unique WITHIN an organization, not globally. This
    lets org "acme" have a "prod" project and org "globex" also have a
    "prod" project — they don't conflict.
    """

    __tablename__ = "projects"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    organization: Mapped[Organization] = relationship(
        "Organization",
        back_populates="projects",
        lazy="raise",
    )
    api_keys: Mapped[list[APIKey]] = relationship(
        "APIKey",
        back_populates="project",
        lazy="raise",
    )
    routes: Mapped[list[Route]] = relationship(
        "Route",
        back_populates="project",
        lazy="raise",
    )
    upstreams: Mapped[list[Upstream]] = relationship(
        "Upstream",
        back_populates="project",
        lazy="raise",
    )

    __table_args__ = (
        # Slug is unique within an organization, not globally.
        # Composite unique constraint rather than a unique column.
        UniqueConstraint("organization_id", "slug", name="uq_project_org_slug"),
        Index("ix_projects_organization_id", "organization_id"),
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} slug={self.slug!r}>"
