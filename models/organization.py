from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import HydraSoftDeleteBase

if TYPE_CHECKING:
    from models.membership import OrganizationMembership
    from models.project import Project


class Organization(HydraSoftDeleteBase):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Slug is the URL-safe, human-readable identifier used in API paths:
    #   /api/v1/orgs/{slug}/projects
    # Slugs are globally unique and permanent — changing them would break
    # bookmarked URLs. Separate from `name` so the name can be renamed freely.
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)

    # plan tracks the billing tier. "free" for now; future milestones add
    # rate limiting and feature gating based on this.
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="free")

    memberships: Mapped[list[OrganizationMembership]] = relationship(
        "OrganizationMembership",
        back_populates="organization",
        lazy="raise",
    )
    projects: Mapped[list[Project]] = relationship(
        "Project",
        back_populates="organization",
        lazy="raise",
    )

    __table_args__ = (Index("ix_organizations_slug", "slug"),)

    def __repr__(self) -> str:
        return f"<Organization id={self.id} slug={self.slug!r}>"
