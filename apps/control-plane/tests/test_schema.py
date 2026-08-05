from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlmodel import SQLModel

import control_plane
from control_plane.models.tombstone import TOMBSTONE_COLUMNS, tombstoned_models, tombstoned_tables

CONTROL_PLANE_DIR = Path(control_plane.__file__).resolve().parents[2]


def _migrated_engine(tmp_path):
    config = Config(str(CONTROL_PLANE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_PLANE_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{tmp_path}/migrated.db")
    command.upgrade(config, "head")
    return create_engine(f"sqlite:///{tmp_path}/migrated.db")


def test_tombstoned_models_carry_the_columns_in_metadata():
    tables = tombstoned_tables()
    assert tables
    for table in tables:
        assert set(table.c.keys()) >= TOMBSTONE_COLUMNS, table.name


def test_tombstonable_models_inherit_the_lifecycle_fields():
    models = tombstoned_models()
    assert models
    for cls in models:
        assert set(cls.model_fields) >= TOMBSTONE_COLUMNS, cls.__name__


def test_migrated_tables_carry_the_tombstone_columns(tmp_path):
    inspector = inspect(_migrated_engine(tmp_path))
    for table in tombstoned_tables():
        columns = {column["name"] for column in inspector.get_columns(table.name)}
        assert columns >= TOMBSTONE_COLUMNS, table.name


def test_migrations_produce_the_model_schema(tmp_path):
    engine = _migrated_engine(tmp_path)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), SQLModel.metadata)
    assert diff == []


def _triggers(engine) -> dict[str, str]:
    with engine.connect() as connection:
        return {row[0]: row[1] for row in connection.execute(text("select name, sql from sqlite_master where type = 'trigger'"))}


def test_touch_triggers_match_between_schema_paths(tmp_path):
    created = create_engine(f"sqlite:///{tmp_path}/created.db")
    SQLModel.metadata.create_all(created)
    created_triggers = _triggers(created)
    migrated_triggers = _triggers(_migrated_engine(tmp_path))
    assert created_triggers == migrated_triggers
    for table in tombstoned_tables():
        assert f"{table.name}_touch_insert" in created_triggers, table.name
        assert f"{table.name}_touch_update" in created_triggers, table.name
