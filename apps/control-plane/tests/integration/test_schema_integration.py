from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from pg import db_name_for, drop_database, ensure_database
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

import control_plane
from control_plane.models.audit import audit_trigger_ddl_v1, audited_tables
from control_plane.models.bundle_input import bundle_input_tables, bundle_input_trigger_ddl_v1
from control_plane.models.common.identified import UUIDV7_SHIM_DDL_V1, needs_uuidv7_shim
from control_plane.models.common.tombstone import TOMBSTONE_COLUMNS, tombstoned_tables, touch_trigger_ddl_v1

CONTROL_PLANE_DIR = Path(control_plane.__file__).resolve().parents[2]


@pytest.fixture
def pg_db(tmp_path):
    """Named scratch databases beyond the test's standard one, dropped at teardown."""
    created = []

    def make(suffix: str) -> str:
        name = f"{db_name_for(tmp_path)}_{suffix}"
        created.append(name)
        return ensure_database(name)

    yield make
    for name in created:
        drop_database(name)


def _migrated_url(pg_db) -> str:
    url = pg_db("migrated")
    config = Config(str(CONTROL_PLANE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_PLANE_DIR / "src" / "control_plane" / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return url


def _run_sync(url: str, fn):
    async def run():
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(fn)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _triggers(conn) -> dict[str, str]:
    """Trigger and trigger-function definitions, keyed by name; our trigger names embed the table."""
    triggers = conn.execute(text("SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger WHERE NOT tgisinternal"))
    functions = conn.execute(
        text(
            "SELECT proname, pg_get_functiondef(oid) FROM pg_proc "
            "WHERE proname LIKE 'touch_timestamps%' OR proname LIKE 'audit_row%' OR proname LIKE 'mark_bundle_stale%'"
        )
    )
    return {row[0]: row[1] for row in [*triggers, *functions]}


def _current_trigger_ddl() -> list[str]:
    """The triggers the current DDL versions produce over the current model set; the intent side of the parity test."""
    touch = [statement for table in tombstoned_tables() for statement in touch_trigger_ddl_v1(table.name)]
    audit = [
        statement
        for table in audited_tables()
        for statement in audit_trigger_ddl_v1(table.name, tuple(column.name for column in table.primary_key.columns))
    ]
    bundle_input = [
        statement for table, spec in bundle_input_tables() for statement in bundle_input_trigger_ddl_v1(table.name, spec.scope, spec.ignored_columns)
    ]
    return [*touch, *audit, *bundle_input]


def _created_triggers(url: str) -> dict[str, str]:
    async def create_all() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                if await conn.run_sync(needs_uuidv7_shim):
                    await conn.exec_driver_sql(UUIDV7_SHIM_DDL_V1)
                await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS citext")
                await conn.run_sync(SQLModel.metadata.create_all)
                for statement in _current_trigger_ddl():
                    await conn.exec_driver_sql(statement)
        finally:
            await engine.dispose()

    asyncio.run(create_all())
    return _run_sync(url, _triggers)


def test_migrated_tables_carry_the_tombstone_columns(pg_db):
    """The migration chain, run from an empty database, produces the lifecycle columns."""
    url = _migrated_url(pg_db)
    columns_by_table = _run_sync(url, lambda conn: {t.name: {c["name"] for c in inspect(conn).get_columns(t.name)} for t in tombstoned_tables()})
    for table in tombstoned_tables():
        assert columns_by_table[table.name] >= TOMBSTONE_COLUMNS, table.name


def test_migrations_produce_the_model_schema(pg_db):
    """The migrated schema is identical to the models: a hand-written migration that drifts fails here."""
    url = _migrated_url(pg_db)
    diff = _run_sync(url, lambda conn: compare_metadata(MigrationContext.configure(conn), SQLModel.metadata))
    assert diff == []


def test_policy_access_paths_are_indexed_in_models_and_migrations(pg_db):
    expected = {
        "policy_active_org_id_idx",
        "policy_active_workspace_id_idx",
        "policy_workspace_priority_id_idx",
    }
    assert {index.name for index in SQLModel.metadata.tables["policy"].indexes} >= expected
    url = _migrated_url(pg_db)
    migrated = _run_sync(url, lambda conn: {index["name"] for index in inspect(conn).get_indexes("policy")})
    assert migrated >= expected


def test_case_insensitive_identifiers_use_citext_in_models_and_migrations(pg_db):
    expected = {
        ("org", "slug"),
        ("provider", "name"),
        ("provider_credential", "name"),
        ("org_invitation", "email"),
        ("user", "email"),
        ("workspace", "slug"),
    }
    model_columns = {
        (table_name, column)
        for table_name, column in expected
        if SQLModel.metadata.tables[table_name].c[column].type.__class__.__name__.lower() == "citext"
    }
    url = _migrated_url(pg_db)

    def migrated_columns(conn):
        rows = conn.execute(
            text("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' AND udt_name = 'citext'")
        )
        return set(rows)

    assert model_columns == expected
    assert _run_sync(url, migrated_columns) == expected


def test_migrations_install_the_current_trigger_schema(pg_db):
    created_triggers = _created_triggers(pg_db("created"))
    migrated_triggers = _run_sync(_migrated_url(pg_db), _triggers)
    assert created_triggers == migrated_triggers
    for table in tombstoned_tables():
        assert f"{table.name}_touch_insert" in created_triggers, table.name
        assert f"{table.name}_touch_update" in created_triggers, table.name


def test_database_mints_uuid7_ids_for_raw_inserts(pg_db):
    """The uuidv7() server default is the backstop: a write path that skips the ORM still gets a time-ordered id."""
    url = _migrated_url(pg_db)

    def raw_insert(conn):
        conn.execute(text("SELECT set_config('app.user_id', 'schema-test', true)"))
        row = conn.execute(text("INSERT INTO \"user\" (email, name, service_account) VALUES ('raw@example.com', 'raw', false) RETURNING id"))
        return row.scalar_one()

    minted = _run_sync(url, raw_insert)
    assert minted.version == 7


def test_audit_triggers_cover_every_audited_table(pg_db):
    """Every @audited model gets its audit trigger from the current DDL; the parity test above pins the migration path to it."""
    created_triggers = _created_triggers(pg_db("created"))
    tables = audited_tables()
    assert tables
    for table in tables:
        assert f"{table.name}_audit" in created_triggers, table.name


def test_bundle_input_triggers_cover_every_declared_table(pg_db):
    created_triggers = _created_triggers(pg_db("created"))
    tables = bundle_input_tables()
    assert tables
    for table, _ in tables:
        assert f"{table.name}_bundle_stale" in created_triggers, table.name
