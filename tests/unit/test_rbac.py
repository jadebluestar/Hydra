"""
Unit tests for RBAC permission mapping and scope validation.
Zero infrastructure required.
"""

import pytest

from domain.enums.permission import Permission
from domain.enums.role import Role
from domain.enums.scope import APIKeyScope
from security.rbac import ROLE_PERMISSIONS, get_permissions, has_permission, require_permission
from security.scopes import has_scope, validate_requested_scopes

# ── Role → Permission mapping ─────────────────────────────────────────────────


class TestRolePermissions:
    def test_owner_has_all_permissions(self) -> None:
        owner_perms = get_permissions(Role.OWNER)
        for perm in Permission:
            assert perm in owner_perms, f"Owner is missing: {perm}"

    def test_viewer_cannot_mutate_anything(self) -> None:
        viewer_perms = get_permissions(Role.VIEWER)
        mutating = {
            Permission.CREATE_PROJECT,
            Permission.DELETE_PROJECT,
            Permission.INVITE_MEMBER,
            Permission.REMOVE_MEMBER,
            Permission.CREATE_ROUTE,
            Permission.DELETE_ROUTE,
            Permission.ROTATE_API_KEY,
        }
        for perm in mutating:
            assert perm not in viewer_perms, f"Viewer should not have: {perm}"

    def test_viewer_can_read_everything(self) -> None:
        viewer_perms = get_permissions(Role.VIEWER)
        read_only = {
            Permission.VIEW_PROJECT,
            Permission.VIEW_API_KEYS,
            Permission.VIEW_ROUTES,
            Permission.VIEW_ANALYTICS,
            Permission.VIEW_LOGS,
            Permission.VIEW_METRICS,
        }
        for perm in read_only:
            assert perm in viewer_perms, f"Viewer should have: {perm}"

    def test_admin_cannot_transfer_ownership(self) -> None:
        admin_perms = get_permissions(Role.ADMIN)
        assert Permission.TRANSFER_OWNERSHIP not in admin_perms

    def test_admin_cannot_delete_organization(self) -> None:
        admin_perms = get_permissions(Role.ADMIN)
        assert Permission.DELETE_ORGANIZATION not in admin_perms

    def test_member_cannot_manage_members(self) -> None:
        member_perms = get_permissions(Role.MEMBER)
        assert Permission.INVITE_MEMBER not in member_perms
        assert Permission.REMOVE_MEMBER not in member_perms
        assert Permission.UPDATE_MEMBER_ROLE not in member_perms

    def test_member_can_manage_routes(self) -> None:
        member_perms = get_permissions(Role.MEMBER)
        assert Permission.CREATE_ROUTE in member_perms
        assert Permission.DELETE_ROUTE in member_perms

    def test_permission_sets_are_frozen(self) -> None:
        for role, perms in ROLE_PERMISSIONS.items():
            assert isinstance(perms, frozenset), f"{role} permissions are not a frozenset"


class TestHasPermission:
    def test_returns_true_when_role_has_permission(self) -> None:
        assert has_permission(Role.ADMIN, Permission.CREATE_PROJECT) is True

    def test_returns_false_when_role_lacks_permission(self) -> None:
        assert has_permission(Role.VIEWER, Permission.CREATE_PROJECT) is False

    def test_owner_has_every_permission(self) -> None:
        for perm in Permission:
            assert has_permission(Role.OWNER, perm) is True


class TestRequirePermission:
    def test_does_not_raise_when_permitted(self) -> None:
        require_permission(Role.ADMIN, Permission.CREATE_PROJECT)  # no exception

    def test_raises_forbidden_when_not_permitted(self) -> None:
        from core.exceptions import ForbiddenError

        with pytest.raises(ForbiddenError):
            require_permission(Role.VIEWER, Permission.DELETE_PROJECT)

    def test_error_message_includes_role_and_permission(self) -> None:
        from core.exceptions import ForbiddenError

        with pytest.raises(ForbiddenError) as exc_info:
            require_permission(Role.VIEWER, Permission.CREATE_PROJECT)

        assert "viewer" in str(exc_info.value).lower()
        assert "create_project" in str(exc_info.value).lower()


# ── Scope validation ──────────────────────────────────────────────────────────


class TestHasScope:
    def test_exact_scope_match(self) -> None:
        assert has_scope(["gateway:read"], APIKeyScope.GATEWAY_READ) is True

    def test_scope_not_granted(self) -> None:
        assert has_scope(["gateway:read"], APIKeyScope.GATEWAY_WRITE) is False

    def test_gateway_write_implies_gateway_read(self) -> None:
        # A key with write access can also read
        assert has_scope(["gateway:write"], APIKeyScope.GATEWAY_READ) is True

    def test_admin_implies_all_scopes(self) -> None:
        for scope in APIKeyScope:
            assert has_scope(["admin"], scope) is True, f"admin should imply {scope}"

    def test_empty_scopes_returns_false(self) -> None:
        assert has_scope([], APIKeyScope.GATEWAY_READ) is False

    def test_multiple_scopes_any_match(self) -> None:
        assert has_scope(["analytics:read", "gateway:read"], APIKeyScope.ANALYTICS_READ) is True

    def test_analytics_does_not_imply_gateway(self) -> None:
        assert has_scope(["analytics:read"], APIKeyScope.GATEWAY_READ) is False


class TestValidateRequestedScopes:
    def test_valid_scopes_pass(self) -> None:
        result = validate_requested_scopes(["gateway:read", "analytics:read"])
        assert result == ["gateway:read", "analytics:read"]

    def test_unrecognized_scope_raises(self) -> None:
        with pytest.raises(ValueError, match="Unrecognized scope"):
            validate_requested_scopes(["gateway:read", "not_a_real_scope"])

    def test_empty_list_is_valid(self) -> None:
        result = validate_requested_scopes([])
        assert result == []

    def test_all_defined_scopes_are_valid(self) -> None:
        all_scopes = [s.value for s in APIKeyScope]
        result = validate_requested_scopes(all_scopes)
        assert result == all_scopes
