from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Sequence, Table, event, func, inspect, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from sqlmodel import Field, SQLModel, col, select

from control_plane.db import current_session
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.global_runtime_configuration import GlobalRuntimeConfiguration

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import InstanceState

type RuntimeConfigurationScope = Literal["global", "org", "nullable_org"]
type PublicationState = Literal["current", "pending", "failed"]

CONFIGURATION_REVISION_SEQUENCE = Sequence("configuration_revision_seq", metadata=SQLModel.metadata)


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


class PublishedBundleOut(BaseModel):
    id: UUID
    version: int
    issued_at: datetime


class PublicationFailureOut(BaseModel):
    category: str
    message: str


class BundlePublicationStatusOut(BaseModel):
    desired_revision: int
    published_revision: int
    status: PublicationState
    latest_bundle: PublishedBundleOut | None
    last_attempt_at: datetime | None
    failure: PublicationFailureOut | None


class BundleRepublishOut(BaseModel):
    queued_revision: int
    publication: BundlePublicationStatusOut


class InstancePublicationStatusOut(BaseModel):
    global_desired_revision: int
    pending_organization_count: int
    failed_organization_count: int


def bundle_input[T: Record](*, scope: RuntimeConfigurationScope, columns: tuple[str, ...]) -> Callable[[type[T]], type[T]]:
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


async def next_configuration_revision() -> int:
    return (await current_session().execute(select(CONFIGURATION_REVISION_SEQUENCE.next_value()))).scalar_one()


async def record_runtime_configuration_changes(changes: RuntimeConfigurationChanges) -> int | None:
    if not changes:
        return None
    revision = await next_configuration_revision()
    if changes.global_scope:
        await GlobalRuntimeConfiguration.advance(revision)
    if changes.org_ids:
        from control_plane.models.org import Org  # noqa: PLC0415 runtime configuration depends on the completed model graph

        existing_org_ids = (await current_session().execute(select(Org.id).where(col(Org.id).in_(changes.org_ids)))).scalars().all()
        if existing_org_ids:
            values = tuple({"org_id": org_id, "desired_revision": revision} for org_id in existing_org_ids)
            insert = pg_insert(RuntimeConfiguration).values(values)
            statement = insert.on_conflict_do_update(
                index_elements=["org_id"],
                set_={"desired_revision": func.greatest(col(RuntimeConfiguration.desired_revision), insert.excluded.desired_revision)},
            )
            await current_session().execute(statement)
    return revision


class RuntimeConfiguration(Record, table=True):
    org_id: UUID = Field(primary_key=True, foreign_key="org.id", ondelete="CASCADE")
    desired_revision: int = 0
    published_revision: int = 0
    last_attempted_revision: int | None = None
    last_attempted_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    failure_count: int = 0
    next_attempt_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    last_error_category: str | None = Field(default=None, max_length=50)
    last_error_message: str | None = Field(default=None, max_length=200)

    @classmethod
    async def request_republication(cls, org_id: UUID) -> int:
        revision = await next_configuration_revision()
        insert = pg_insert(cls).values(org_id=org_id, desired_revision=revision)
        statement = insert.on_conflict_do_update(
            index_elements=["org_id"], set_={"desired_revision": func.greatest(col(cls.desired_revision), insert.excluded.desired_revision)}
        )
        await current_session().execute(statement)
        return revision

    @classmethod
    async def ensure(cls, org_id: UUID) -> RuntimeConfiguration:
        await current_session().execute(pg_insert(cls).values(org_id=org_id).on_conflict_do_nothing(index_elements=["org_id"]))
        configuration = await cls.get(org_id)
        if configuration is None:
            msg = f"runtime configuration missing for organization {org_id}"
            raise RuntimeError(msg)
        return configuration

    @classmethod
    async def next_pending(cls, now: datetime) -> tuple[UUID, int] | None:
        from control_plane.models.org import Org  # noqa: PLC0415 runtime configuration depends on the completed model graph

        global_revision = await GlobalRuntimeConfiguration.desired()
        target = func.greatest(global_revision, func.coalesce(cls.desired_revision, 0))
        published = func.coalesce(cls.published_revision, 0)
        due = col(cls.next_attempt_at).is_(None) | col(cls.last_attempted_revision).is_distinct_from(target) | (col(cls.next_attempt_at) <= now)
        query = (
            select(Org.id, target.label("target_revision"))
            .outerjoin(cls, col(cls.org_id) == col(Org.id))
            .where(target > published, due)
            .order_by(col(Org.id))
            .limit(1)
        )
        candidate = (await current_session().execute(query)).one_or_none()
        return (candidate[0], candidate[1]) if candidate is not None else None

    @classmethod
    async def try_lock(cls, org_id: UUID) -> bool:
        statement = text("SELECT pg_try_advisory_xact_lock(hashtextextended(CAST(:org_id AS text), 0))")
        return bool((await current_session().execute(statement, {"org_id": str(org_id)})).scalar_one())

    @classmethod
    async def target(cls, org_id: UUID) -> tuple[RuntimeConfiguration, int]:
        configuration = await cls.ensure(org_id)
        return configuration, max(await GlobalRuntimeConfiguration.desired(), configuration.desired_revision)

    async def mark_published(self, revision: int, now: datetime) -> None:
        self.published_revision = revision
        self.last_attempted_revision = revision
        self.last_attempted_at = now
        self.failure_count = 0
        self.next_attempt_at = None
        self.last_error_category = None
        self.last_error_message = None
        await self.save()

    @classmethod
    async def record_failure(cls, org_id: UUID, revision: int, now: datetime) -> None:
        from control_plane.models.org import Org  # noqa: PLC0415 runtime configuration depends on the completed model graph

        organization = (await current_session().execute(select(Org.id).where(Org.id == org_id).with_for_update(key_share=True))).scalar_one_or_none()
        if organization is None:
            return
        configuration, target = await cls.target(org_id)
        if target != revision or configuration.published_revision >= target:
            return
        failure_count = configuration.failure_count + 1 if configuration.last_attempted_revision == revision else 1
        configuration.last_attempted_revision = revision
        configuration.last_attempted_at = now
        configuration.failure_count = failure_count
        configuration.next_attempt_at = now + timedelta(seconds=min(2 ** (failure_count - 1), 60))
        configuration.last_error_category = "compilation_failed"
        configuration.last_error_message = "Configuration could not be published"
        await configuration.save()

    @classmethod
    async def status(cls, org_id: UUID) -> BundlePublicationStatusOut:
        from control_plane.models.bundle import Bundle  # noqa: PLC0415 runtime configuration status includes bundle history

        configuration = await cls.get(org_id)
        global_revision = await GlobalRuntimeConfiguration.desired()
        desired_revision = max(global_revision, configuration.desired_revision if configuration is not None else 0)
        published_revision = configuration.published_revision if configuration is not None else 0
        failed = (
            configuration is not None
            and configuration.last_attempted_revision == desired_revision
            and configuration.failure_count > 0
            and published_revision < desired_revision
        )
        state: PublicationState = "current" if published_revision >= desired_revision else "failed" if failed else "pending"
        latest = await Bundle.first(Bundle.org_id == org_id, order_by=col(Bundle.version).desc())
        return BundlePublicationStatusOut(
            desired_revision=desired_revision,
            published_revision=published_revision,
            status=state,
            latest_bundle=PublishedBundleOut(id=latest.id, version=latest.version, issued_at=latest.issued_at) if latest is not None else None,
            last_attempt_at=configuration.last_attempted_at if configuration is not None else None,
            failure=(
                PublicationFailureOut(category=configuration.last_error_category, message=configuration.last_error_message)
                if failed and configuration.last_error_category is not None and configuration.last_error_message is not None
                else None
            ),
        )

    @classmethod
    async def instance_status(cls) -> InstancePublicationStatusOut:
        from control_plane.models.org import Org  # noqa: PLC0415 runtime configuration depends on the completed model graph

        global_revision = await GlobalRuntimeConfiguration.desired()
        target = func.greatest(global_revision, func.coalesce(cls.desired_revision, 0))
        published = func.coalesce(cls.published_revision, 0)
        failed = (target > published) & (cls.last_attempted_revision == target) & (func.coalesce(cls.failure_count, 0) > 0)
        query = (
            select(
                func.count().filter((target > published) & ~failed),
                func.count().filter(failed),
            )
            .select_from(Org)
            .outerjoin(cls, col(cls.org_id) == col(Org.id))
        )
        pending_count, failed_count = (await current_session().execute(query)).one()
        return InstancePublicationStatusOut(
            global_desired_revision=global_revision,
            pending_organization_count=pending_count,
            failed_organization_count=failed_count,
        )


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
