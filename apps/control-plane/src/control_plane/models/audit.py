from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Table, inspect, text
from sqlmodel import Field

from control_plane.db import current_session
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime

if TYPE_CHECKING:
    from uuid import UUID

_AUDITED: set[type[Record]] = set()

ACTOR_GUC = "app.user_id"


def audited[T: Record](cls: type[T]) -> type[T]:
    """Marks a table for audit coverage.

    This registry is the source the audit trigger DDL is generated from: database triggers write
    the AuditLog rows on every write path, including Core statements the ORM never sees. The
    acting user reaches the triggers through the transaction-local ACTOR_GUC set_actor stamps.
    Never write AuditLog rows by hand.
    """
    _AUDITED.add(cls)
    return cls


class AuditLog(Record, table=True):
    id: int | None = Field(default=None, primary_key=True)
    table_name: str
    record_id: str
    action: str
    user_id: str
    before: dict[str, Any] | None = Field(default=None, sa_type=JSON)
    after: dict[str, Any] | None = Field(default=None, sa_type=JSON)
    occurred_at: datetime = Field(sa_type=UTCDateTime)


def audit_trigger_ddl_v1(table: str, pk_columns: tuple[str, ...]) -> tuple[str, str]:
    """Audit triggers write the AuditLog row for any write to an audited table, whoever wrote it.

    Versioned and frozen like touch_trigger_ddl_v1: migrations import this by version, so its
    output can never change. One shared AFTER trigger function; the primary key columns arrive
    as trigger arguments so record_id joins them in declaration order, matching the old ORM
    listener. Snapshots exclude the database-owned tombstone timestamps. The actor comes from
    the transaction-local GUC and is mandatory: an unset or empty actor raises, so an audited
    write can never land unattributed.
    """
    function = (
        "CREATE OR REPLACE FUNCTION audit_row_v1() RETURNS trigger LANGUAGE plpgsql AS $$ "  # noqa: S608 the interpolated GUC name is our own constant, not user input
        "DECLARE source jsonb; rid text; actor text; BEGIN "
        f"actor := NULLIF(current_setting('{ACTOR_GUC}', true), ''); "
        "IF actor IS NULL THEN RAISE EXCEPTION 'unattributed write to audited table %, call set_actor first', TG_TABLE_NAME; END IF; "
        "IF TG_OP = 'DELETE' THEN source := to_jsonb(OLD); ELSE source := to_jsonb(NEW); END IF; "
        "SELECT string_agg(source ->> pk, '/' ORDER BY ord) INTO rid FROM unnest(TG_ARGV) WITH ORDINALITY AS t(pk, ord); "
        "INSERT INTO audit_log (table_name, record_id, action, user_id, before, after, occurred_at) VALUES ("
        "TG_TABLE_NAME, rid, "
        "CASE TG_OP WHEN 'INSERT' THEN 'create' WHEN 'UPDATE' THEN 'update' ELSE 'delete' END, "
        "actor, "
        "(CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE to_jsonb(OLD) - 'created_at' - 'updated_at' - 'deleted_at' END)::json, "
        "(CASE WHEN TG_OP = 'DELETE' THEN NULL ELSE to_jsonb(NEW) - 'created_at' - 'updated_at' - 'deleted_at' END)::json, "
        "now()); RETURN NULL; END $$"
    )
    columns = ", ".join(f"'{column}'" for column in pk_columns)
    trigger = (
        f'CREATE OR REPLACE TRIGGER {table}_audit AFTER INSERT OR UPDATE OR DELETE ON "{table}" FOR EACH ROW EXECUTE FUNCTION audit_row_v1({columns})'
    )
    return function, trigger


def audit_trigger_drop_ddl_v1(table: str) -> tuple[str, str]:
    """The inverse of audit_trigger_ddl_v1, for migration downgrades. Versioned and frozen like it.

    Mirrors the creation side's idempotence like touch_trigger_drop_ddl_v1: the function drop is
    guarded on no remaining triggers, so the last table's drop sweeps the function away.
    """
    drop_trigger = f'DROP TRIGGER IF EXISTS {table}_audit ON "{table}"'
    drop_function = (
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_trigger t JOIN pg_proc p ON t.tgfoid = p.oid "
        "WHERE p.proname = 'audit_row_v1' AND NOT t.tgisinternal) "
        "THEN DROP FUNCTION IF EXISTS audit_row_v1(); END IF; END $$"
    )
    return drop_trigger, drop_function


def audited_tables() -> list[Table]:
    mappers = (inspect(cls, raiseerr=False) for cls in _AUDITED)
    return sorted(
        (table for mapper in mappers if mapper is not None and isinstance(table := mapper.persist_selectable, Table)),
        key=lambda table: table.name,
    )


async def set_actor(user_id: UUID | str) -> None:
    """Stamp the transaction-local GUC the audit triggers read as the acting user.

    Call it wherever identity is established, before the first audited write of the unit of
    work. Transaction-local means the stamp dies at commit, so a pooled connection can never
    leak an actor into the next request, and every transaction attributes explicitly or not at
    all. Goes through the Core connection so it can never autoflush writes that predate it.
    """
    connection = await current_session().connection()
    await connection.execute(text("SELECT set_config(:guc, :actor, true)"), {"guc": ACTOR_GUC, "actor": str(user_id)})
