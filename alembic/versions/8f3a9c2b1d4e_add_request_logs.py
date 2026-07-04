"""add request_logs table

Revision ID: 8f3a9c2b1d4e
Revises: 2c7912e0dc45
Create Date: 2026-07-03 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "8f3a9c2b1d4e"
down_revision: str | None = "2c7912e0dc45"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "request_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        # Soft references — no FK constraints so logs outlive deleted entities
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Request
        sa.Column("http_method", sa.String(10), nullable=False),
        sa.Column("path", sa.String(2048), nullable=False),
        sa.Column("client_ip", sa.String(45), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False, server_default=""),
        # Response
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("upstream_latency_ms", sa.Integer(), nullable=True),
        sa.Column("total_latency_ms", sa.Integer(), nullable=False),
        sa.Column("is_rate_limited", sa.Boolean(), nullable=False, server_default="false"),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Primary query: "requests for this project, newest first"
    op.create_index(
        "ix_request_logs_project_created",
        "request_logs",
        ["project_id", "created_at"],
    )
    # Secondary: "requests from this API key"
    op.create_index(
        "ix_request_logs_api_key_id",
        "request_logs",
        ["api_key_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_request_logs_api_key_id", table_name="request_logs")
    op.drop_index("ix_request_logs_project_created", table_name="request_logs")
    op.drop_table("request_logs")
