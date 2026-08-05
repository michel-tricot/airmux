from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import JSON, event, inspect
from sqlalchemy.orm import Session
from sqlmodel import Field

from control_plane.db import current_actor
from control_plane.models.base import Record
from control_plane.models.tombstone import TOMBSTONE_COLUMNS

_AUDITED: set[type[Record]] = set()

AUDITED_DIALECTS = frozenset({"sqlite"})


def audited[T: Record](cls: type[T]) -> type[T]:
    """Marks a table for audit coverage.

    On SQLite the flush listener below writes the AuditLog rows; on Postgres audit will move to
    database triggers generated from this registry (see notes/IDEAS.md), and the listener no-ops.
    Never write AuditLog rows by hand, and remember Core statements bypass the ORM audit.
    """
    _AUDITED.add(cls)
    return cls


class AuditLog(Record, table=True):
    id: int | None = Field(default=None, primary_key=True)
    table_name: str
    record_id: str
    action: str
    user_id: str | None = None
    before: dict[str, Any] | None = Field(default=None, sa_type=JSON)
    after: dict[str, Any] | None = Field(default=None, sa_type=JSON)
    occurred_at: datetime


def _entry(obj: Record, action: str, before: dict[str, Any] | None, after: dict[str, Any] | None, now: datetime) -> AuditLog:
    mapper = inspect(type(obj))
    record_id = "/".join(str(getattr(obj, mapper.get_property_by_column(column).key)) for column in mapper.primary_key)
    actor = current_actor.get()
    return AuditLog(
        table_name=mapper.persist_selectable.name, record_id=record_id, action=action, user_id=actor, before=before, after=after, occurred_at=now
    )


def _snapshot(obj: Record) -> dict[str, Any]:
    """Business fields only: the lifecycle timestamps are database-owned and stale on the ORM side."""
    return jsonable_encoder(obj.model_dump(exclude=set(TOMBSTONE_COLUMNS)))


def _snapshot_before(obj: Record) -> dict[str, Any]:
    state = inspect(obj)
    if state is None:
        return _snapshot(obj)
    old = {
        attr.key: attr.history.deleted[0]
        for attr in state.attrs
        if attr.key not in TOMBSTONE_COLUMNS and attr.history.has_changes() and attr.history.deleted
    }
    return jsonable_encoder({**obj.model_dump(exclude=set(TOMBSTONE_COLUMNS)), **old})


@event.listens_for(Session, "before_flush")
def _audit_before_flush(session: Session, _flush_context: object, _instances: object) -> None:
    if session.get_bind().dialect.name not in AUDITED_DIALECTS:
        return
    now = datetime.now(tz=UTC)
    updated = [obj for obj in session.dirty if type(obj) in _AUDITED and session.is_modified(obj)]
    entries = [
        *[_entry(obj, "create", None, _snapshot(obj), now) for obj in session.new if type(obj) in _AUDITED],
        *[_entry(obj, "update", _snapshot_before(obj), _snapshot(obj), now) for obj in updated],
        *[_entry(obj, "delete", _snapshot(obj), None, now) for obj in session.deleted if type(obj) in _AUDITED],
    ]
    session.add_all(entries)
