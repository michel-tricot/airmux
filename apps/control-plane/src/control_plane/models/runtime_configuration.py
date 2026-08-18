from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from sqlalchemy import Table, event, inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from sqlmodel import Field, col, literal, select

from control_plane.db import current_session
from control_plane.models.common.base import Record

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import InstanceState


type RuntimeConfigurationScope = Literal["global", "org", "nullable_org"]


@dataclass(frozen=True)
class RuntimeConfigurationInput:
    model: type[Record]
    scope: RuntimeConfigurationScope
    columns: tuple[str, ...]


_RUNTIME_CONFIGURATION_INPUTS: dict[type[Record], RuntimeConfigurationInput] = {}
_RUNTIME_CONFIGURATION_CHANGES = "runtime_configuration_changes"


@dataclass(frozen=True)
class RuntimeConfigurationChanges:
    global_scope: bool = False
    org_ids: frozenset[UUID] = frozenset()

    def merged(self, other: RuntimeConfigurationChanges) -> RuntimeConfigurationChanges:
        return RuntimeConfigurationChanges(
            global_scope=self.global_scope or other.global_scope,
            org_ids=self.org_ids | other.org_ids,
        )

    def __bool__(self) -> bool:
        return self.global_scope or bool(self.org_ids)


def runtime_configured[T: Record](*, scope: RuntimeConfigurationScope, columns: tuple[str, ...]) -> Callable[[type[T]], type[T]]:
    def register(cls: type[T]) -> type[T]:
        _RUNTIME_CONFIGURATION_INPUTS[cls] = RuntimeConfigurationInput(model=cls, scope=scope, columns=columns)
        return cls

    return register


@event.listens_for(Session, "before_flush")
def _remember_runtime_configuration_changes(session: Session, _flush_context: object, _instances: object) -> None:
    created_or_deleted = session.new.union(session.deleted)
    changes = RuntimeConfigurationChanges()
    for entity in created_or_deleted.union(session.dirty):
        configuration_input = _RUNTIME_CONFIGURATION_INPUTS.get(type(entity))
        if configuration_input is None:
            continue
        state = inspect(entity)
        if entity not in created_or_deleted and not any(state.attrs[column].history.has_changes() for column in configuration_input.columns):
            continue
        changes = changes.merged(_changes_for(entity, configuration_input))
    if changes:
        previous = session.info.get(_RUNTIME_CONFIGURATION_CHANGES, RuntimeConfigurationChanges())
        session.info[_RUNTIME_CONFIGURATION_CHANGES] = previous.merged(changes)


def _changes_for(entity: Record, configuration_input: RuntimeConfigurationInput) -> RuntimeConfigurationChanges:
    if configuration_input.scope == "global":
        return RuntimeConfigurationChanges(global_scope=True)
    state = cast("InstanceState[Record]", inspect(entity))
    owner_history = state.attrs.org_id.history
    owners = (*owner_history.deleted, *owner_history.added, *owner_history.unchanged)
    if configuration_input.scope == "nullable_org" and None in owners:
        return RuntimeConfigurationChanges(global_scope=True)
    return RuntimeConfigurationChanges(org_ids=frozenset(owner for owner in owners if owner is not None))


def runtime_configuration_changes(session: Session) -> RuntimeConfigurationChanges:
    return session.info.pop(_RUNTIME_CONFIGURATION_CHANGES, RuntimeConfigurationChanges())


class RuntimeConfiguration(Record, table=True):
    org_id: UUID = Field(primary_key=True, foreign_key="org.id", ondelete="CASCADE")
    desired_revision: int = 0
    published_revision: int = 0

    @classmethod
    async def advance(cls, changes: RuntimeConfigurationChanges) -> None:
        if not changes:
            return
        from control_plane.models.org import Org  # noqa: PLC0415 runtime configuration depends on the completed model graph

        revisions = select(
            col(Org.id).label("org_id"),
            literal(1).label("desired_revision"),
            literal(0).label("published_revision"),
        )
        if not changes.global_scope:
            revisions = revisions.where(col(Org.id).in_(changes.org_ids))
        statement = pg_insert(cls).from_select(("org_id", "desired_revision", "published_revision"), revisions)
        statement = statement.on_conflict_do_update(
            index_elements=["org_id"],
            set_={"desired_revision": col(cls.desired_revision) + 1},
        )
        await current_session().execute(statement)

    @classmethod
    async def request_republication(cls, org_id: UUID) -> None:
        await cls.advance(RuntimeConfigurationChanges(org_ids=frozenset({org_id})))

    @classmethod
    async def for_update(cls, org_id: UUID) -> RuntimeConfiguration:
        session = current_session()
        await session.execute(pg_insert(cls).values(org_id=org_id).on_conflict_do_nothing(index_elements=["org_id"]))
        return (await session.execute(select(cls).where(cls.org_id == org_id).with_for_update())).scalar_one()

    @classmethod
    async def next_pending(cls) -> RuntimeConfiguration | None:
        query = (
            select(cls)
            .where(col(cls.desired_revision) > col(cls.published_revision))
            .order_by(col(cls.org_id))
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        return (await current_session().execute(query)).scalar_one_or_none()


def runtime_configuration_inputs() -> list[tuple[Table, RuntimeConfigurationInput]]:
    return sorted(
        (
            (table, configuration_input)
            for configuration_input in _RUNTIME_CONFIGURATION_INPUTS.values()
            if (mapper := inspect(configuration_input.model, raiseerr=False)) is not None
            if isinstance(table := mapper.persist_selectable, Table)
        ),
        key=lambda entry: entry[0].name,
    )
