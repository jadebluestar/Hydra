"""
SQLAlchemy declarative base and model mixins.

All Hydra models inherit from HydraBase or HydraSoftDeleteBase — never from
Base directly. This guarantees every table gets:
  - A UUIDv7 primary key (time-ordered, B-tree-friendly)
  - created_at and updated_at audit timestamps
  - Optionally: deleted_at for soft deletion

Naming conventions on MetaData are critical for Alembic. Without them,
constraint names are auto-generated non-deterministically. Alembic cannot
produce reliable ALTER TABLE statements (e.g., DROP CONSTRAINT) without a
name it can predict. Our conventions produce names like:
    fk_org_members_user_id_users
    uq_users_email
    ix_routes_project_id
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from utils.uuidv7 import uuid7

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """
    Root declarative base with consistent constraint naming.

    Every SQLAlchemy model in Hydra inherits from this class through
    HydraBase or HydraSoftDeleteBase.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# ── Mixins ────────────────────────────────────────────────────────────────────


class UUIDMixin:
    """
    Adds a UUIDv7 primary key column named 'id'.

    sort_order=-10 ensures 'id' is always the first column in DDL output,
    regardless of how Python's MRO orders the class attributes.

    Why not auto-increment integers?
      - UUIDs are globally unique — safe to generate in the application before
        writing to the database, useful for distributed systems.
      - UUIDv7's time-ordered prefix prevents B-tree index page splits, giving
        the write performance of sequences with the uniqueness of UUIDs.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid7,
        sort_order=-10,
    )


class TimestampMixin:
    """
    Adds created_at and updated_at immutable audit timestamps.

    created_at:
      server_default=func.now() — PostgreSQL sets this on INSERT.
      Never changes after the row is created.

    updated_at:
      server_default=func.now() — PostgreSQL sets this on INSERT.
      onupdate callback — Python sets this to UTC now() on every UPDATE.

    Using server_default (rather than Python's datetime.now()) means the
    database clock is authoritative. In a multi-server deployment, application
    clocks can drift; the database clock is always consistent.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        sort_order=998,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        sort_order=999,
    )


class SoftDeleteMixin:
    """
    Adds soft deletion via a nullable deleted_at timestamp.

    Hard deleting a user or organization would cascade to or orphan every
    related record (projects, API keys, routes, logs). Soft deletion avoids
    this by keeping the row present and only marking it as inactive.

    Soft delete also gives you:
    - Exact timestamp of when the resource was removed
    - Ability to undo accidental deletions (restore())
    - Referential integrity: foreign keys in other tables still resolve

    All queries on soft-deletable models must filter WHERE deleted_at IS NULL.
    A future milestone adds a SQLAlchemy event listener to apply this
    automatically, so callers never forget.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        sort_order=1000,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """Mark this record as deleted. The caller must flush/commit the session."""
        self.deleted_at = datetime.now(UTC)

    def restore(self) -> None:
        """Undo a soft deletion."""
        self.deleted_at = None


# ── Concrete base classes ─────────────────────────────────────────────────────


class HydraBase(UUIDMixin, TimestampMixin, Base):
    """
    Standard base for models that do NOT support soft deletion.

    Use for: audit_logs, request_logs, analytics_daily, refresh_tokens.
    These are event records — they should never be "deleted," only queried.
    """

    __abstract__ = True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id}>"


class HydraSoftDeleteBase(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """
    Base for models that support soft deletion.

    Use for: users, organizations, projects, api_keys, routes, upstreams.
    Anything a user can "delete" through the API.
    """

    __abstract__ = True

    def __repr__(self) -> str:
        suffix = " [DELETED]" if self.is_deleted else ""
        return f"<{self.__class__.__name__} id={self.id}{suffix}>"
