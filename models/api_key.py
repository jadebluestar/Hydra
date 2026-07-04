from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import HydraBase

if TYPE_CHECKING:
    from models.project import Project
    from models.user import User


class APIKey(HydraBase):
    """
    An API key authenticates gateway traffic.

    Security model (GitHub personal access token pattern):
      1. On creation, generate the full key: "hk_live_<32 random hex chars>"
      2. Store ONLY the prefix (first 16 chars) for display: "hk_live_abc12345"
      3. Store an Argon2 hash of the full key for verification
      4. Return the full key to the caller EXACTLY ONCE — they must save it

    Why Argon2 for API keys and not just SHA256?
      SHA256 is fast — an attacker with the key_hash could brute-force
      the key space very quickly if they get DB read access. Argon2id
      makes each guess expensive. For high-entropy keys (32 random hex chars)
      SHA256 is arguably fine, but Argon2id is our standard and consistent.

    Revocation uses `revoked_at` (not soft delete) because:
      - We want to show revoked keys in the UI with their revocation timestamp
      - Soft delete (deleted_at) implies the record is gone; revocation is
        a meaningful state transition that operators need to see
    """

    __tablename__ = "api_keys"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Human label for this key — e.g., "Mobile app production"
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # First 16 chars of the full key, shown in the UI after creation.
    # Format: "hk_live_abc12345" (hk = hydra key, then environment, then prefix)
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)

    # Argon2id hash of the full key.
    # The gateway verifies inbound requests by: hashing the bearer token
    # and comparing against this field. Never the plaintext.
    key_hash: Mapped[str] = mapped_column(String(1024), nullable=False)

    # Scopes this key is authorized for: ["gateway:read", "analytics:read"]
    # JSONB: binary JSON in PostgreSQL — indexable and queryable with @> operator
    scopes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )

    # Optional expiry. None = never expires.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(
        "Project",
        back_populates="api_keys",
        lazy="raise",
    )
    created_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[created_by_id],
        lazy="raise",
    )

    __table_args__ = (
        # The gateway looks up keys by prefix first (fast), then verifies the
        # hash. Prefix lookup narrows the candidate set before the slow hash check.
        Index("ix_api_keys_key_prefix", "key_prefix"),
        Index("ix_api_keys_project_id", "project_id"),
    )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        from datetime import datetime as dt

        return dt.now(UTC) > self.expires_at

    @property
    def is_active(self) -> bool:
        return not self.is_revoked and not self.is_expired

    def __repr__(self) -> str:
        return f"<APIKey id={self.id} prefix={self.key_prefix!r} active={self.is_active}>"
