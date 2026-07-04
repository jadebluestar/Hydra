"""
Unit tests for domain value objects and enums.
Zero infrastructure required.
"""

import pytest

from domain.enums import APIKeyScope, CircuitState, Permission, Role
from domain.value_objects import Email, RoutePath

# ── Email ─────────────────────────────────────────────────────────────────────


class TestEmail:
    def test_valid_email_is_accepted(self) -> None:
        email = Email("alice@example.com")
        assert email.value == "alice@example.com"

    def test_email_is_normalized_to_lowercase(self) -> None:
        email = Email("ALICE@EXAMPLE.COM")
        assert email.value == "alice@example.com"

    def test_email_strips_surrounding_whitespace(self) -> None:
        email = Email("  alice@example.com  ")
        assert email.value == "alice@example.com"

    def test_equality_by_value(self) -> None:
        assert Email("alice@example.com") == Email("alice@example.com")

    def test_case_normalized_emails_are_equal(self) -> None:
        assert Email("ALICE@EXAMPLE.COM") == Email("alice@example.com")

    def test_different_emails_are_not_equal(self) -> None:
        assert Email("alice@example.com") != Email("bob@example.com")

    def test_email_is_immutable(self) -> None:
        email = Email("alice@example.com")
        with pytest.raises((AttributeError, TypeError)):
            email.value = "bob@example.com"  # type: ignore[misc]

    def test_str_returns_value(self) -> None:
        email = Email("alice@example.com")
        assert str(email) == "alice@example.com"

    def test_domain_property(self) -> None:
        assert Email("alice@example.com").domain == "example.com"

    def test_local_part_property(self) -> None:
        assert Email("alice@example.com").local_part == "alice"

    def test_email_can_be_used_as_dict_key(self) -> None:
        d = {Email("alice@example.com"): "user_id"}
        assert d[Email("alice@example.com")] == "user_id"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            Email("")

    def test_missing_at_sign_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid email"):
            Email("notanemail")

    def test_missing_domain_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid email"):
            Email("alice@")

    def test_missing_tld_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid email"):
            Email("alice@example")


# ── RoutePath ─────────────────────────────────────────────────────────────────


class TestRoutePath:
    def test_valid_path_is_accepted(self) -> None:
        path = RoutePath("/api/v1/users")
        assert path.value == "/api/v1/users"

    def test_trailing_slash_is_stripped(self) -> None:
        assert RoutePath("/api/v1/users/").value == "/api/v1/users"

    def test_root_path_is_preserved(self) -> None:
        assert RoutePath("/").value == "/"

    def test_double_slash_only_raises(self) -> None:
        # "//" starts with "/" but is still a double slash — invalid
        with pytest.raises(ValueError, match="must not contain"):
            RoutePath("//")

    def test_equality_by_value(self) -> None:
        assert RoutePath("/users") == RoutePath("/users")

    def test_trailing_slash_equals_without(self) -> None:
        assert RoutePath("/users/") == RoutePath("/users")

    def test_path_is_immutable(self) -> None:
        path = RoutePath("/users")
        with pytest.raises((AttributeError, TypeError)):
            path.value = "/something-else"  # type: ignore[misc]

    def test_str_returns_value(self) -> None:
        assert str(RoutePath("/api")) == "/api"

    def test_segments_property(self) -> None:
        assert RoutePath("/api/v1/users").segments == ["api", "v1", "users"]

    def test_root_segments_is_empty_list(self) -> None:
        assert RoutePath("/").segments == []

    def test_missing_leading_slash_raises(self) -> None:
        with pytest.raises(ValueError, match="must start with"):
            RoutePath("api/users")

    def test_empty_path_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            RoutePath("")

    def test_double_slash_raises(self) -> None:
        with pytest.raises(ValueError, match="must not contain"):
            RoutePath("/api//users")

    def test_is_prefix_of_matching_path(self) -> None:
        assert RoutePath("/api").is_prefix_of("/api/users") is True

    def test_is_prefix_of_exact_match(self) -> None:
        assert RoutePath("/api").is_prefix_of("/api") is True

    def test_is_prefix_of_mid_segment_match_is_false(self) -> None:
        # "/api" should NOT match "/apikeys" — not a segment boundary
        assert RoutePath("/api").is_prefix_of("/apikeys") is False

    def test_root_is_prefix_of_everything(self) -> None:
        assert RoutePath("/").is_prefix_of("/anything/at/all") is True


# ── Enums ─────────────────────────────────────────────────────────────────────


class TestRoleEnum:
    def test_role_values_are_strings(self) -> None:
        assert Role.OWNER == "owner"
        assert Role.ADMIN == "admin"
        assert Role.MEMBER == "member"
        assert Role.VIEWER == "viewer"

    def test_role_from_string(self) -> None:
        assert Role("owner") is Role.OWNER

    def test_all_roles_are_unique(self) -> None:
        values = [r.value for r in Role]
        assert len(values) == len(set(values))


class TestPermissionEnum:
    def test_permissions_are_strings(self) -> None:
        assert Permission.CREATE_PROJECT == "create_project"

    def test_all_permissions_are_unique(self) -> None:
        values = [p.value for p in Permission]
        assert len(values) == len(set(values))

    def test_permission_count_is_expected(self) -> None:
        # Catch accidental duplicate or missing entries
        assert len(Permission) == 25


class TestAPIScopeEnum:
    def test_scope_colon_format(self) -> None:
        assert APIKeyScope.GATEWAY_READ == "gateway:read"
        assert APIKeyScope.GATEWAY_WRITE == "gateway:write"
        assert APIKeyScope.ADMIN == "admin"

    def test_all_scopes_are_unique(self) -> None:
        values = [s.value for s in APIKeyScope]
        assert len(values) == len(set(values))


class TestCircuitStateEnum:
    def test_state_values(self) -> None:
        assert CircuitState.CLOSED == "closed"
        assert CircuitState.OPEN == "open"
        assert CircuitState.HALF_OPEN == "half_open"


# ── Provider Protocols ────────────────────────────────────────────────────────


class TestProviderProtocols:
    """
    Verify that runtime_checkable protocols work and that concrete
    implementations satisfy them structurally.
    """

    def test_jwt_provider_protocol_is_runtime_checkable(self) -> None:
        from providers.interfaces import JWTProvider

        class FakeJWT:
            def encode(self, payload: dict) -> str:
                return "token"

            def decode(self, token: str) -> dict:
                return {}

        assert isinstance(FakeJWT(), JWTProvider)

    def test_hashing_provider_protocol_is_runtime_checkable(self) -> None:
        from providers.interfaces import HashingProvider

        class FakeHasher:
            async def hash(self, plaintext: str) -> str:
                return "hashed"

            async def verify(self, plaintext: str, hashed: str) -> bool:
                return True

            async def needs_rehash(self, hashed: str) -> bool:
                return False

        assert isinstance(FakeHasher(), HashingProvider)

    def test_email_provider_protocol_is_runtime_checkable(self) -> None:
        from providers.interfaces import EmailProvider

        class FakeEmail:
            async def send(self, *, to: str, subject: str, body_text: str, body_html=None) -> None:
                pass

        assert isinstance(FakeEmail(), EmailProvider)

    def test_missing_method_fails_isinstance_check(self) -> None:
        from providers.interfaces import JWTProvider

        class IncompleteJWT:
            def encode(self, payload: dict) -> str:  # missing decode
                return "token"

        assert not isinstance(IncompleteJWT(), JWTProvider)
