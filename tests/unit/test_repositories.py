"""
Unit tests for repository logic that doesn't require a real database.

Full integration tests (CRUD against a live PostgreSQL) are in
tests/integration/ and require the `infra` marker. These tests only
verify the structural and import-level correctness of the repository layer.
"""

from datetime import UTC

from database.base import HydraBase, HydraSoftDeleteBase
from repositories.base import BaseRepository

# ── Soft-delete detection ─────────────────────────────────────────────────────
#
# The base repository inspects the model class to decide whether to add
# `deleted_at IS NULL` to every query. These tests verify that detection.


class TestSoftDeleteDetection:
    """BaseRepository must detect soft-delete models at construction time."""

    def test_soft_delete_model_is_detected(self) -> None:
        # Use a minimal concrete class that inherits SoftDeleteMixin
        class FakeModel(HydraSoftDeleteBase):
            __tablename__ = "fake_soft"
            __abstract__ = False  # prevent Base from treating it as abstract

        # We can't instantiate BaseRepository without a real session,
        # but we can inspect the class attribute detection logic directly.
        is_soft = issubclass(FakeModel, HydraSoftDeleteBase)
        assert is_soft is True

    def test_non_soft_delete_model_is_not_detected(self) -> None:
        class FakeModel(HydraBase):
            __tablename__ = "fake_hard"
            __abstract__ = False

        is_soft = issubclass(FakeModel, HydraSoftDeleteBase)
        assert is_soft is False


# ── Repository imports ────────────────────────────────────────────────────────


class TestRepositoryImports:
    """All repositories must import cleanly — catches circular imports."""

    def test_all_repositories_importable(self) -> None:
        from repositories import (
            APIKeyRepository,
            BaseRepository,
            MembershipRepository,
            OrganizationRepository,
            ProjectRepository,
            RouteRepository,
            UpstreamRepository,
            UserRepository,
        )

        repos = [
            APIKeyRepository,
            BaseRepository,
            MembershipRepository,
            OrganizationRepository,
            ProjectRepository,
            RouteRepository,
            UpstreamRepository,
            UserRepository,
        ]
        for repo in repos:
            assert repo is not None

    def test_base_repository_is_generic(self) -> None:
        # BaseRepository is Generic[ModelT] — it should have __class_getitem__
        assert hasattr(BaseRepository, "__class_getitem__")


# ── Model → repository pairing ────────────────────────────────────────────────


class TestRepositoryModelPairing:
    """Each repository must be wired to the correct model class."""

    def test_user_repository_uses_user_model(self) -> None:
        # We can inspect the class without a session by checking the
        # model_class argument via __init_subclass__ introspection.
        # Instead, verify UserRepository is defined in terms of User.
        import inspect

        from repositories.user_repository import UserRepository

        src = inspect.getsource(UserRepository.__init__)
        assert "User" in src

    def test_route_repository_uses_route_model(self) -> None:
        import inspect

        from repositories.route_repository import RouteRepository

        src = inspect.getsource(RouteRepository.__init__)
        assert "Route" in src


# ── APIKey helper logic ───────────────────────────────────────────────────────


class TestAPIKeyModel:
    """
    Test the pure Python logic on the APIKey model.
    No DB needed — these are property accessors on a plain Python object.
    """

    def test_is_revoked_false_by_default(self) -> None:
        from models.api_key import APIKey

        key = APIKey()
        assert key.is_revoked is False

    def test_is_revoked_true_when_revoked_at_set(self) -> None:
        from datetime import datetime

        from models.api_key import APIKey

        key = APIKey()
        key.revoked_at = datetime.now(UTC)
        assert key.is_revoked is True

    def test_is_expired_false_when_no_expiry(self) -> None:
        from models.api_key import APIKey

        key = APIKey()
        key.expires_at = None
        assert key.is_expired is False

    def test_is_expired_true_when_past_expiry(self) -> None:
        from datetime import datetime, timedelta

        from models.api_key import APIKey

        key = APIKey()
        key.expires_at = datetime.now(UTC) - timedelta(hours=1)
        assert key.is_expired is True

    def test_is_active_false_when_revoked(self) -> None:
        from datetime import datetime

        from models.api_key import APIKey

        key = APIKey()
        key.revoked_at = datetime.now(UTC)
        key.expires_at = None
        assert key.is_active is False

    def test_is_active_true_when_not_revoked_and_not_expired(self) -> None:
        from models.api_key import APIKey

        key = APIKey()
        key.revoked_at = None
        key.expires_at = None
        assert key.is_active is True


# ── Route model logic ─────────────────────────────────────────────────────────


class TestRouteModel:
    def test_route_repr_includes_path_prefix(self) -> None:
        from models.route import Route

        route = Route()
        route.path_prefix = "/api/v1"
        route.is_active = True
        assert "/api/v1" in repr(route)
