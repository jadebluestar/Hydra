"""initial schema

Revision ID: 2c7912e0dc45
Revises:
Create Date: 2026-06-30

Creates the full initial schema:
  users, organizations, organization_memberships,
  projects, api_keys, upstreams, routes
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2c7912e0dc45"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(1024), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_email_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index(
        "ix_users_active",
        "users",
        ["is_active"],
        postgresql_where=sa.text("is_active = TRUE AND deleted_at IS NULL"),
    )

    # ── organizations ──────────────────────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("plan", sa.String(50), nullable=False, server_default="free"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])

    # ── organization_memberships ───────────────────────────────────────────────
    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("invited_by_id", sa.UUID(), nullable=True),
        sa.Column("role", sa.String(50), nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organization_memberships"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_organization_memberships_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_organization_memberships_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_id"],
            ["users.id"],
            name="fk_organization_memberships_invited_by_id_users",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
    )

    # ── projects ───────────────────────────────────────────────────────────────
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_projects_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("organization_id", "slug", name="uq_project_org_slug"),
    )
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"])

    # ── upstreams ──────────────────────────────────────────────────────────────
    op.create_table(
        "upstreams",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_upstreams"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_upstreams_project_id_projects",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_upstreams_project_id", "upstreams", ["project_id"])

    # ── api_keys ───────────────────────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(32), nullable=False),
        sa.Column("key_hash", sa.String(1024), nullable=False),
        sa.Column("scopes", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_api_keys_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_api_keys_created_by_id_users",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"])
    op.create_index("ix_api_keys_project_id", "api_keys", ["project_id"])

    # ── routes ─────────────────────────────────────────────────────────────────
    op.create_table(
        "routes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("upstream_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("path_prefix", sa.String(2048), nullable=False),
        sa.Column("methods", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("required_scope", sa.String(50), nullable=True),
        sa.Column("strip_prefix", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("rate_limit_rpm", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_routes"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_routes_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["upstream_id"],
            ["upstreams.id"],
            name="fk_routes_upstream_id_upstreams",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_routes_project_id", "routes", ["project_id"])
    op.create_index("ix_routes_path_prefix", "routes", ["path_prefix"])
    op.create_index("ix_routes_upstream_id", "routes", ["upstream_id"])


def downgrade() -> None:
    # Drop in reverse dependency order: children before parents
    op.drop_table("routes")
    op.drop_table("api_keys")
    op.drop_table("upstreams")
    op.drop_table("projects")
    op.drop_table("organization_memberships")
    op.drop_table("organizations")
    op.drop_table("users")
