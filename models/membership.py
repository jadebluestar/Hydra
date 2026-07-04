from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import HydraBase

if TYPE_CHECKING:
    from models.organization import Organization
    from models.user import User


class OrganizationMembership(HydraBase):
    """
    The join between a User and an Organization, carrying the member's Role.

    This is a "rich join table" — it's not just a foreign key pair, it has
    its own data (role, joined_at, who invited them). That's why it gets
    its own model class instead of a SQLAlchemy secondary table.

    We use HydraBase (no soft delete) because membership revocation should
    be a hard delete. Keeping deleted memberships would require filtering
    them out of every query that touches members. If you need an audit trail,
    emit a domain event instead (Milestone 19).

    UNIQUE(organization_id, user_id): a user can only be a member of an
    org once. Adding them twice would create duplicate permission entries.
    """

    __tablename__ = "organization_memberships"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Stored as the string value of the Role enum: "owner", "admin", etc.
    # Using String (not Enum column type) means adding new roles doesn't
    # require a DB migration — just update the Python enum.
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")

    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Two FKs point to the users table: user_id and invited_by_id.
    # SQLAlchemy requires `foreign_keys=` to resolve the ambiguity — otherwise
    # it can't determine which FK to use for which relationship direction.
    organization: Mapped[Organization] = relationship(
        "Organization",
        back_populates="memberships",
        lazy="raise",
    )
    user: Mapped[User] = relationship(
        "User",
        back_populates="memberships",
        foreign_keys=[user_id],
        lazy="raise",
    )
    invited_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[invited_by_id],
        lazy="raise",
    )

    __table_args__ = (
        # A user can only hold one role per org. Attempting to add them twice
        # raises an IntegrityError — the service catches this as ConflictError.
        UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
    )

    def __repr__(self) -> str:
        return (
            f"<OrganizationMembership "
            f"org={self.organization_id} user={self.user_id} role={self.role!r}>"
        )
