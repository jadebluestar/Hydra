"""
Role-Based Access Control.

Maps each Role to a frozenset of Permissions. All checks go through
has_permission() — never compare roles directly in service code.

Why frozensets?
  - Immutable: the mapping cannot be accidentally modified at runtime
  - O(1) membership test: `permission in role_permissions` is a hash lookup
  - Set semantics: frozenset(Permission) gives OWNER literally all permissions
    without listing them one by one — if a new permission is added, OWNER
    automatically receives it

Design philosophy:
  - OWNER gets everything. They own the organization.
  - ADMIN can manage the product (projects, routes, keys) but cannot
    destroy the organization or transfer ownership.
  - MEMBER can operate the gateway (routes, upstreams, keys) but cannot
    manage other members or organization settings.
  - VIEWER can read everything but cannot mutate anything.

This is intentionally conservative. It is easier to grant more permissions
later than to explain to a customer why their Viewer-role user deleted a route.
"""

from domain.enums.permission import Permission
from domain.enums.role import Role

# The full set of all permissions — used to grant OWNER everything.
_ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: _ALL_PERMISSIONS,
    Role.ADMIN: frozenset(
        {
            # Organization
            Permission.UPDATE_ORGANIZATION,
            # Members
            Permission.INVITE_MEMBER,
            Permission.REMOVE_MEMBER,
            Permission.UPDATE_MEMBER_ROLE,
            Permission.VIEW_MEMBERS,
            # Projects
            Permission.CREATE_PROJECT,
            Permission.UPDATE_PROJECT,
            Permission.DELETE_PROJECT,
            Permission.VIEW_PROJECT,
            # API Keys
            Permission.CREATE_API_KEY,
            Permission.DELETE_API_KEY,
            Permission.ROTATE_API_KEY,
            Permission.VIEW_API_KEYS,
            # Routes
            Permission.CREATE_ROUTE,
            Permission.UPDATE_ROUTE,
            Permission.DELETE_ROUTE,
            Permission.VIEW_ROUTES,
            # Upstreams
            Permission.CREATE_UPSTREAM,
            Permission.UPDATE_UPSTREAM,
            Permission.DELETE_UPSTREAM,
            # Observability
            Permission.VIEW_ANALYTICS,
            Permission.VIEW_LOGS,
            Permission.VIEW_METRICS,
        }
    ),
    Role.MEMBER: frozenset(
        {
            # Projects
            Permission.VIEW_PROJECT,
            # API Keys
            Permission.CREATE_API_KEY,
            Permission.DELETE_API_KEY,
            Permission.ROTATE_API_KEY,
            Permission.VIEW_API_KEYS,
            # Routes
            Permission.CREATE_ROUTE,
            Permission.UPDATE_ROUTE,
            Permission.DELETE_ROUTE,
            Permission.VIEW_ROUTES,
            # Upstreams
            Permission.CREATE_UPSTREAM,
            Permission.UPDATE_UPSTREAM,
            Permission.DELETE_UPSTREAM,
            # Observability
            Permission.VIEW_ANALYTICS,
            Permission.VIEW_LOGS,
            Permission.VIEW_METRICS,
        }
    ),
    Role.VIEWER: frozenset(
        {
            Permission.VIEW_MEMBERS,
            Permission.VIEW_PROJECT,
            Permission.VIEW_API_KEYS,
            Permission.VIEW_ROUTES,
            Permission.VIEW_ANALYTICS,
            Permission.VIEW_LOGS,
            Permission.VIEW_METRICS,
        }
    ),
}


def get_permissions(role: Role) -> frozenset[Permission]:
    """Return the full set of permissions granted to a role."""
    return ROLE_PERMISSIONS[role]


def has_permission(role: Role, permission: Permission) -> bool:
    """
    Return True if the role grants the given permission.

    Usage in service layer:
        if not rbac.has_permission(member.role, Permission.DELETE_PROJECT):
            raise ForbiddenError("You do not have permission to delete projects")
    """
    return permission in ROLE_PERMISSIONS[role]


def require_permission(role: Role, permission: Permission) -> None:
    """
    Raise ForbiddenError if the role does not have the permission.

    A convenience wrapper that keeps service code concise:
        rbac.require_permission(member.role, Permission.INVITE_MEMBER)
        # continues only if permitted

    Imports ForbiddenError lazily to avoid circular imports between
    the security and core layers.
    """
    if not has_permission(role, permission):
        from core.exceptions import ForbiddenError

        raise ForbiddenError(
            f"Role '{role}' does not have permission: {permission}"
        )
