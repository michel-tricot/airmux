from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import DDL, Table, event, func, inspect
from sqlmodel import Field, SQLModel

TOMBSTONE_COLUMNS = frozenset({"created_at", "updated_at", "deleted_at"})


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


class Tombstonable(SQLModel):
    """Lifecycle timestamps for every tombstonable table; models inherit these fields and never declare them.

    The database owns these values through the touch triggers below: updated_at is never
    null, equals created_at on creation, and refreshes on every update. deleted_at stays null under
    SQLite, which hard-deletes; trigger-based soft delete arrives with Postgres, see notes/IDEAS.md.
    The field defaults are placeholders that satisfy NOT NULL until the insert trigger overwrites them.
    """

    created_at: datetime = Field(default_factory=utcnow, sa_column_kwargs={"server_default": func.now()})
    updated_at: datetime = Field(default_factory=utcnow, sa_column_kwargs={"server_default": func.now()})
    deleted_at: datetime | None = None

    api_readonly: ClassVar[frozenset[str]] = TOMBSTONE_COLUMNS


def touch_trigger_ddl_v1(table: str) -> tuple[str, str]:
    """Touch triggers make the database own the lifecycle timestamps, whatever wrote the row.

    Versioned and frozen: alembic migrations import this by version, so its output can never change.
    To evolve the trigger SQL, add touch_trigger_ddl_v2, point install_touch_triggers at it, and
    write a new migration that drops the old triggers and creates the new ones.

    The WHEN guard on the update trigger skips rows whose updated_at was already changed by the
    firing statement, which makes the pair recursion-proof without relying on PRAGMA settings.
    """
    now = "STRFTIME('%Y-%m-%d %H:%M:%f', 'now')"
    on_insert = (
        f'CREATE TRIGGER IF NOT EXISTS {table}_touch_insert AFTER INSERT ON "{table}" BEGIN '  # noqa: S608 table names come from our own metadata, not user input
        f'UPDATE "{table}" SET (created_at, updated_at) = (SELECT n, n FROM (SELECT {now} AS n)) WHERE rowid = NEW.rowid; END'
    )
    on_update = (
        f'CREATE TRIGGER IF NOT EXISTS {table}_touch_update AFTER UPDATE ON "{table}" '  # noqa: S608 table names come from our own metadata, not user input
        f"WHEN NEW.updated_at IS OLD.updated_at BEGIN "
        f'UPDATE "{table}" SET updated_at = {now} WHERE rowid = NEW.rowid; END'
    )
    return on_insert, on_update


def install_touch_triggers() -> None:
    """Attach the current trigger version to each tombstoned table so create_all installs them.

    A version bump here requires a migration doing the same swap; test_schema proves both paths agree.
    """
    for table in tombstoned_tables():
        for statement in touch_trigger_ddl_v1(table.name):
            escaped = statement.replace("%", "%%")
            event.listen(table, "after_create", DDL(escaped).execute_if(dialect="sqlite"))


def tombstoned_models() -> list[type[Tombstonable]]:
    return _descendants(Tombstonable)


def tombstoned_tables() -> list[Table]:
    mappers = (inspect(cls, raiseerr=False) for cls in tombstoned_models())
    return [table for mapper in mappers if mapper is not None and isinstance(table := mapper.persist_selectable, Table)]


def _descendants(cls: type[Tombstonable]) -> list[type[Tombstonable]]:
    return [sub for child in cls.__subclasses__() for sub in (child, *_descendants(child))]
