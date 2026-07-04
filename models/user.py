from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import HydraSoftDeleteBase

if TYPE_CHECKING:
    from models.membership import OrganizationMembership


class User(HydraSoftDeleteBase):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(1024), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships — lazy="raise" requires explicit loading via selectinload()
    # in repositories. Accessing these without loading raises immediately
    # instead of silently firing a sync query that would fail in async context.
    memberships: Mapped[list[OrganizationMembership]] = relationship(
        "OrganizationMembership",
        back_populates="user",
        foreign_keys="OrganizationMembership.user_id",
        lazy="raise",
    )

    __table_args__ = (
        # Covering index — most user lookups are by email (login, invite lookup)
        Index("ix_users_email", "email"),
        # Partial index: only index active, non-deleted users for auth queries.
        # The gateway only cares about active users; inactive users are rare.
        Index(
            "ix_users_active",
            "is_active",
            postgresql_where="is_active = TRUE AND deleted_at IS NULL",
        ),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
