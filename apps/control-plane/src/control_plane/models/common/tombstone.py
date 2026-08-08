from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import Table, func, inspect
from sqlmodel import Field, SQLModel

from control_plane.models.common.column_types import UTCDateTime

TOMBSTONE_COLUMNS = frozenset({"created_at", "updated_at", "deleted_at"})


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


class Tombstonable(SQLModel):
    """Lifecycle timestamps for every tombstonable table; models inherit these fields and never declare them.

    The database owns these values through the touch triggers below: updated_at is never
    null, equals created_at on creation, and refreshes on every update. deleted_at stays null
    for now: deletes are hard until trigger-based soft delete lands, see notes/IDEAS.md.
    The field defaults are placeholders that satisfy NOT NULL until the insert trigger overwrites them.
    """

    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime, sa_column_kwargs={"server_default": func.now()})
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime, sa_column_kwargs={"server_default": func.now()})
    deleted_at: datetime | None = Field(default=None, sa_type=UTCDateTime)

    api_readonly: ClassVar[frozenset[str]] = TOMBSTONE_COLUMNS


def touch_trigger_ddl_v1(table: str) -> tuple[str, str, str]:
    """Touch triggers make the database own the lifecycle timestamps, whatever wrote the row.

    Versioned and frozen: alembic migrations import this by version, so its output can never change.
    To evolve the trigger SQL, add touch_trigger_ddl_v2, point test_schema's trigger install at it,
    and write a new migration that drops the old triggers and creates the new ones.

    One shared BEFORE trigger function, a pair of triggers per table. The function statement is
    idempotent so every table can carry it; BEFORE triggers rewrite NEW in place, which makes the
    pair recursion-proof by construction. The IS NOT DISTINCT FROM guard means a statement that
    explicitly sets updated_at wins.
    """
    function = (
        "CREATE OR REPLACE FUNCTION touch_timestamps_v1() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "IF TG_OP = 'INSERT' THEN NEW.created_at := now(); NEW.updated_at := NEW.created_at; "
        "ELSIF NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at THEN NEW.updated_at := now(); END IF; "
        "RETURN NEW; END $$"
    )
    on_insert = f'CREATE OR REPLACE TRIGGER {table}_touch_insert BEFORE INSERT ON "{table}" FOR EACH ROW EXECUTE FUNCTION touch_timestamps_v1()'
    on_update = f'CREATE OR REPLACE TRIGGER {table}_touch_update BEFORE UPDATE ON "{table}" FOR EACH ROW EXECUTE FUNCTION touch_timestamps_v1()'
    return function, on_insert, on_update


def tombstoned_models() -> list[type[Tombstonable]]:
    return _descendants(Tombstonable)


def tombstoned_tables() -> list[Table]:
    mappers = (inspect(cls, raiseerr=False) for cls in tombstoned_models())
    return [table for mapper in mappers if mapper is not None and isinstance(table := mapper.persist_selectable, Table)]


def _descendants(cls: type[Tombstonable]) -> list[type[Tombstonable]]:
    return [sub for child in cls.__subclasses__() for sub in (child, *_descendants(child))]
