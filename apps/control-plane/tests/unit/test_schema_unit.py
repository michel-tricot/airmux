from __future__ import annotations

from pathlib import Path

import control_plane
from control_plane.models.bundle_input import bundle_input_tables
from control_plane.models.common.tombstone import TOMBSTONE_COLUMNS, tombstoned_models, tombstoned_tables

CONTROL_PLANE_DIR = Path(control_plane.__file__).resolve().parents[2]


def test_pre_release_schema_has_one_baseline_migration():
    migrations = list((CONTROL_PLANE_DIR / "src" / "control_plane" / "migrations" / "versions").glob("*.py"))
    assert [migration.name for migration in migrations] == ["a9f3c6e1d8b4_initial_schema.py"]


def test_tombstoned_models_carry_the_columns_in_metadata():
    """Every Tombstonable table has creation and update timestamps in its metadata."""
    tables = tombstoned_tables()
    assert tables
    for table in tables:
        assert set(table.c.keys()) >= TOMBSTONE_COLUMNS, table.name
        assert "deleted_at" not in table.c, table.name


def test_tombstonable_models_inherit_the_lifecycle_fields():
    """Every Tombstonable model exposes the lifecycle fields to pydantic, not just to the database."""
    models = tombstoned_models()
    assert models
    for cls in models:
        assert set(cls.model_fields) >= TOMBSTONE_COLUMNS, cls.__name__
        assert "deleted_at" not in cls.model_fields, cls.__name__


def test_bundle_input_registry_names_real_ignored_columns():
    inputs = bundle_input_tables()
    assert inputs
    for table, bundle_input in inputs:
        assert set(bundle_input.ignored_columns) <= set(table.c.keys()), table.name
