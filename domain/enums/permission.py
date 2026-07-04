"""
Granular permission definitions.

Rather than checking `user.role == "admin"`, services check:
    rbac.has_permission(member.role, Permission.DELETE_PROJECT)

Benefits:
  - Adding a new permission requires one line here and one in rbac.py
  - Removing a permission from a role does not touch service code
  - Fine-grained audit logging: log the specific permission that was checked
  - Easy to answer "what can an Admin do?" by reading the RBAC mapping

Permissions are grouped by the resource they protect. This grouping is
only for readability — the RBAC mapping in security/rbac.py defines
which roles have which permissions.
"""

from enum import StrEnum


class Permission(StrEnum):
    # ── Organization ──────────────────────────────────────────────────────────
    UPDATE_ORGANIZATION = "update_organization"
    DELETE_ORGANIZATION = "delete_organization"
    TRANSFER_OWNERSHIP = "transfer_ownership"

    # ── Members ───────────────────────────────────────────────────────────────
    INVITE_MEMBER = "invite_member"
    REMOVE_MEMBER = "remove_member"
    UPDATE_MEMBER_ROLE = "update_member_role"
    VIEW_MEMBERS = "view_members"

    # ── Projects ──────────────────────────────────────────────────────────────
    CREATE_PROJECT = "create_project"
    UPDATE_PROJECT = "update_project"
    DELETE_PROJECT = "delete_project"
    VIEW_PROJECT = "view_project"

    # ── API Keys ──────────────────────────────────────────────────────────────
    CREATE_API_KEY = "create_api_key"
    DELETE_API_KEY = "delete_api_key"
    ROTATE_API_KEY = "rotate_api_key"
    VIEW_API_KEYS = "view_api_keys"

    # ── Routes ────────────────────────────────────────────────────────────────
    CREATE_ROUTE = "create_route"
    UPDATE_ROUTE = "update_route"
    DELETE_ROUTE = "delete_route"
    VIEW_ROUTES = "view_routes"

    # ── Upstreams ─────────────────────────────────────────────────────────────
    CREATE_UPSTREAM = "create_upstream"
    UPDATE_UPSTREAM = "update_upstream"
    DELETE_UPSTREAM = "delete_upstream"

    # ── Analytics & Observability ─────────────────────────────────────────────
    VIEW_ANALYTICS = "view_analytics"
    VIEW_LOGS = "view_logs"
    VIEW_METRICS = "view_metrics"
