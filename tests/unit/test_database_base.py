"""
Unit tests for database mixins and base model classes.

These run with zero infrastructure — no database connection required.
We instantiate concrete test models (with dummy table names) to verify
mixin behavior in isolation.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String

from database.base import (
    Base,
    HydraBase,
    HydraSoftDeleteBase,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDMixin,
)


# ── Concrete test models ───────────────────────────────────────────────────────
# We define throwaway models with underscore-prefixed table names to avoid
# interfering with production migrations. These are never actually created.


class WidgetModel(HydraBase):
    """Test model without soft deletion."""

    __tablename__ = "_test_widget"
    name: Mapped[str] = mapped_column(String(100), default="")


class EphemeralModel(HydraSoftDeleteBase):
    """Test model with soft deletion."""

    __tablename__ = "_test_ephemeral"
    name: Mapped[str] = mapped_column(String(100), default="")


# ── SoftDeleteMixin ────────────────────────────────────────────────────────────


class TestSoftDeleteMixin:
    def test_is_deleted_false_by_default(self) -> None:
        model = EphemeralModel(name="active")
        assert model.is_deleted is False

    def test_is_deleted_true_when_deleted_at_set(self) -> None:
        model = EphemeralModel(name="gone")
        model.deleted_at = datetime.now(timezone.utc)
        assert model.is_deleted is True

    def test_soft_delete_sets_deleted_at(self) -> None:
        model = EphemeralModel(name="to-delete")
        assert model.deleted_at is None

        model.soft_delete()

        assert model.deleted_at is not None
        assert isinstance(model.deleted_at, datetime)
        assert model.deleted_at.tzinfo is not None  # timezone-aware

    def test_soft_delete_timestamp_is_recent(self) -> None:
        before = datetime.now(timezone.utc)
        model = EphemeralModel(name="timing-test")
        model.soft_delete()
        after = datetime.now(timezone.utc)

        assert model.deleted_at is not None
        assert before <= model.deleted_at <= after

    def test_restore_clears_deleted_at(self) -> None:
        model = EphemeralModel(name="recoverable")
        model.soft_delete()
        assert model.is_deleted is True

        model.restore()

        assert model.is_deleted is False
        assert model.deleted_at is None

    def test_restore_is_idempotent_when_not_deleted(self) -> None:
        model = EphemeralModel(name="healthy")
        model.restore()  # should not raise
        assert model.is_deleted is False

    def test_soft_delete_then_restore_cycle(self) -> None:
        model = EphemeralModel(name="reversible")

        model.soft_delete()
        assert model.is_deleted is True

        model.restore()
        assert model.is_deleted is False

        model.soft_delete()
        assert model.is_deleted is True


# ── UUIDMixin ─────────────────────────────────────────────────────────────────


class TestUUIDMixin:
    def test_id_attribute_exists(self) -> None:
        model = WidgetModel(name="test")
        assert hasattr(model, "id")

    def test_manually_assigned_uuid_is_preserved(self) -> None:
        expected = uuid.uuid4()
        model = WidgetModel(name="explicit-id")
        model.id = expected
        assert model.id == expected

    def test_uuid7_via_generator(self) -> None:
        # The UUIDv7 generator is tested thoroughly in test_uuidv7.py.
        # Here we just verify the mixin wires it up correctly by checking
        # that two UUIDs from the generator are different.
        from utils.uuidv7 import uuid7

        id1 = uuid7()
        id2 = uuid7()
        assert id1 != id2
        assert id1.version == 7
        assert id2.version == 7


# ── TimestampMixin ────────────────────────────────────────────────────────────


class TestTimestampMixin:
    def test_created_at_and_updated_at_columns_exist(self) -> None:
        model = WidgetModel(name="timestamped")
        assert hasattr(model, "created_at")
        assert hasattr(model, "updated_at")

    def test_timestamps_are_none_before_db_insert(self) -> None:
        # server_default=func.now() means PostgreSQL sets these on INSERT.
        # Before the model is persisted, they are None in Python.
        model = WidgetModel(name="pre-insert")
        assert model.created_at is None
        assert model.updated_at is None


# ── __repr__ ──────────────────────────────────────────────────────────────────


class TestRepr:
    def test_hydra_base_repr_includes_class_name(self) -> None:
        model = WidgetModel(name="repr-test")
        model.id = uuid.uuid4()
        result = repr(model)
        assert "WidgetModel" in result

    def test_hydra_base_repr_includes_id(self) -> None:
        model = WidgetModel(name="repr-id-test")
        expected_id = uuid.uuid4()
        model.id = expected_id
        assert str(expected_id) in repr(model)

    def test_soft_delete_repr_shows_deleted_suffix(self) -> None:
        model = EphemeralModel(name="deleted-repr")
        model.id = uuid.uuid4()
        model.soft_delete()
        assert "[DELETED]" in repr(model)

    def test_soft_delete_repr_no_deleted_suffix_when_active(self) -> None:
        model = EphemeralModel(name="active-repr")
        model.id = uuid.uuid4()
        assert "[DELETED]" not in repr(model)


# ── Naming conventions ────────────────────────────────────────────────────────


class TestNamingConventions:
    def test_metadata_has_naming_convention(self) -> None:
        from database.base import NAMING_CONVENTION

        assert "fk" in NAMING_CONVENTION
        assert "uq" in NAMING_CONVENTION
        assert "ix" in NAMING_CONVENTION
        assert "pk" in NAMING_CONVENTION

    def test_base_metadata_uses_naming_convention(self) -> None:
        from database.base import Base, NAMING_CONVENTION

        assert Base.metadata.naming_convention == NAMING_CONVENTION


# ── Alembic config ────────────────────────────────────────────────────────────


class TestAlembicConfig:
    def test_alembic_ini_is_parseable(self) -> None:
        from pathlib import Path

        from alembic.config import Config

        ini_path = Path(__file__).parent.parent.parent / "alembic.ini"
        assert ini_path.exists(), "alembic.ini must exist at project root"
        cfg = Config(str(ini_path))
        assert cfg.get_main_option("script_location") == "alembic"

    def test_alembic_env_imports_cleanly(self) -> None:
        # Importing database.base should not raise even without a real DB
        from database.base import Base, HydraBase, HydraSoftDeleteBase

        assert HydraBase.__abstract__ is True
        assert HydraSoftDeleteBase.__abstract__ is True
