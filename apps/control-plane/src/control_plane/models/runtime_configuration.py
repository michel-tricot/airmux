from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from sqlalchemy import Table, event, inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from sqlmodel import Field, col, select

from control_plane.db import current_session
from control_plane.models.common.base import Record

if TYPE_CHECKING:
    from collections.abc import Callable


type RuntimeConfigurationScope = Literal["global", "org", "nullable_org"]


@dataclass(frozen=True)
class RuntimeConfigurationInput:
    model: type[Record]
    scope: RuntimeConfigurationScope
    columns: tuple[str, ...]


_RUNTIME_CONFIGURATION_INPUTS: dict[type[Record], RuntimeConfigurationInput] = {}
_RUNTIME_CONFIGURATION_CHANGED = "runtime_configuration_changed"


def runtime_configured[T: Record](*, scope: RuntimeConfigurationScope, columns: tuple[str, ...]) -> Callable[[type[T]], type[T]]:
    def register(cls: type[T]) -> type[T]:
        _RUNTIME_CONFIGURATION_INPUTS[cls] = RuntimeConfigurationInput(model=cls, scope=scope, columns=columns)
        return cls

    return register


@event.listens_for(Session, "before_flush")
def _remember_runtime_configuration_changes(session: Session, _flush_context: object, _instances: object) -> None:
    created_or_deleted = session.new.union(session.deleted)
    if any(type(entity) in _RUNTIME_CONFIGURATION_INPUTS for entity in created_or_deleted):
        session.info[_RUNTIME_CONFIGURATION_CHANGED] = True
        return
    for entity in session.dirty:
        configuration_input = _RUNTIME_CONFIGURATION_INPUTS.get(type(entity))
        if configuration_input is None:
            continue
        state = inspect(entity)
        if any(state.attrs[column].history.has_changes() for column in configuration_input.columns):
            session.info[_RUNTIME_CONFIGURATION_CHANGED] = True
            return


def runtime_configuration_changed(session: Session) -> bool:
    return bool(session.info.pop(_RUNTIME_CONFIGURATION_CHANGED, False))


class RuntimeConfiguration(Record, table=True):
    org_id: UUID = Field(primary_key=True, foreign_key="org.id", ondelete="CASCADE")
    desired_revision: int = 0
    published_revision: int = 0

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


def runtime_configuration_trigger_ddl_v1(table: str, scope: RuntimeConfigurationScope, columns: tuple[str, ...]) -> tuple[str, str]:
    function = (
        "CREATE OR REPLACE FUNCTION runtime_configuration_changed_v1() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "DECLARE old_org uuid; new_org uuid; BEGIN "
        "IF TG_ARGV[0] = 'global' THEN "
        "UPDATE runtime_configuration SET desired_revision = desired_revision + 1; RETURN NULL; END IF; "
        "IF TG_OP <> 'INSERT' THEN old_org := NULLIF(to_jsonb(OLD) ->> TG_ARGV[1], '')::uuid; END IF; "
        "IF TG_OP <> 'DELETE' THEN new_org := NULLIF(to_jsonb(NEW) ->> TG_ARGV[1], '')::uuid; END IF; "
        "IF TG_ARGV[0] = 'nullable_org' AND ((TG_OP <> 'INSERT' AND old_org IS NULL) OR (TG_OP <> 'DELETE' AND new_org IS NULL)) THEN "
        "UPDATE runtime_configuration SET desired_revision = desired_revision + 1; RETURN NULL; END IF; "
        "IF old_org IS NOT NULL THEN "
        "INSERT INTO runtime_configuration (org_id, desired_revision, published_revision) VALUES (old_org, 1, 0) "
        "ON CONFLICT (org_id) DO UPDATE SET desired_revision = runtime_configuration.desired_revision + 1; END IF; "
        "IF new_org IS NOT NULL AND new_org IS DISTINCT FROM old_org THEN "
        "INSERT INTO runtime_configuration (org_id, desired_revision, published_revision) VALUES (new_org, 1, 0) "
        "ON CONFLICT (org_id) DO UPDATE SET desired_revision = runtime_configuration.desired_revision + 1; END IF; "
        "RETURN NULL; END $$"
    )
    update_columns = ", ".join(f'"{column}"' for column in columns)
    owner_column = "org_id" if scope != "global" else ""
    trigger = (
        f'CREATE OR REPLACE TRIGGER {table}_runtime_configuration AFTER INSERT OR DELETE OR UPDATE OF {update_columns} ON "{table}" '
        f"FOR EACH ROW EXECUTE FUNCTION runtime_configuration_changed_v1('{scope}', '{owner_column}')"
    )
    return function, trigger


def runtime_configuration_trigger_drop_ddl_v1(table: str) -> tuple[str, str]:
    drop_trigger = f'DROP TRIGGER IF EXISTS {table}_runtime_configuration ON "{table}"'
    drop_function = (
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_trigger t JOIN pg_proc p ON t.tgfoid = p.oid "
        "WHERE p.proname = 'runtime_configuration_changed_v1' AND NOT t.tgisinternal) "
        "THEN DROP FUNCTION IF EXISTS runtime_configuration_changed_v1(); END IF; END $$"
    )
    return drop_trigger, drop_function


def runtime_configuration_seed_trigger_ddl_v1() -> tuple[str, str]:
    function = (
        "CREATE OR REPLACE FUNCTION runtime_configuration_seed_v1() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "INSERT INTO runtime_configuration (org_id, desired_revision, published_revision) VALUES (NEW.id, 0, 0) "
        "ON CONFLICT (org_id) DO NOTHING; RETURN NULL; END $$"
    )
    trigger = (
        'CREATE OR REPLACE TRIGGER org_runtime_configuration_seed AFTER INSERT ON "org" FOR EACH ROW EXECUTE FUNCTION runtime_configuration_seed_v1()'
    )
    return function, trigger


def runtime_configuration_seed_trigger_drop_ddl_v1() -> tuple[str, str]:
    return 'DROP TRIGGER IF EXISTS org_runtime_configuration_seed ON "org"', "DROP FUNCTION IF EXISTS runtime_configuration_seed_v1()"
