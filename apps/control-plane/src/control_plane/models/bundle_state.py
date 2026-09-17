from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Self
from uuid import UUID

from sqlalchemy import BigInteger, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Field, col, select

from control_plane.db import current_session
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.global_bundle_state import GlobalBundleState


@dataclass(frozen=True)
class BundleGenerations:
    global_: int
    org: int


class BundleState(Record, table=True):
    org_id: UUID = Field(primary_key=True, foreign_key="org.id", ondelete="CASCADE")
    desired_generation: int = Field(default=0, sa_type=BigInteger)
    published_global_generation: int = Field(default=-1, sa_type=BigInteger)
    published_org_generation: int = Field(default=-1, sa_type=BigInteger)
    current_bundle_id: UUID | None = Field(default=None, foreign_key="bundle.id", ondelete="SET NULL")
    failed_global_generation: int | None = Field(default=None, sa_type=BigInteger)
    failed_org_generation: int | None = Field(default=None, sa_type=BigInteger)
    failure_count: int = 0
    next_attempt_at: datetime | None = Field(default=None, sa_type=UTCDateTime)

    @classmethod
    async def request_republication(cls, org_id: UUID) -> None:
        insert = pg_insert(cls).values(org_id=org_id, desired_generation=1)
        await current_session().execute(
            insert.on_conflict_do_update(
                index_elements=["org_id"],
                set_={"desired_generation": col(cls.desired_generation) + 1},
            )
        )

    @classmethod
    async def ensure(cls, org_id: UUID) -> Self:
        state = await cls.get(org_id)
        if state is not None:
            return state
        await current_session().execute(pg_insert(cls).values(org_id=org_id).on_conflict_do_nothing(index_elements=["org_id"]))
        state = await cls.get(org_id)
        if state is None:
            msg = f"bundle state missing for organization {org_id}"
            raise RuntimeError(msg)
        return state

    @classmethod
    async def global_generation(cls) -> int:
        state = await current_session().get(GlobalBundleState, 1)
        return state.desired_generation if state is not None else 0

    @classmethod
    async def next_pending(cls, now: datetime) -> UUID | None:
        from control_plane.models.org import Org  # noqa: PLC0415 bundle state depends on the completed model graph

        global_generation = await cls.global_generation()
        desired_org = func.coalesce(cls.desired_generation, 0)
        stale = (
            col(cls.current_bundle_id).is_(None)
            | col(cls.org_id).is_(None)
            | (func.coalesce(cls.published_global_generation, -1) != global_generation)
            | (func.coalesce(cls.published_org_generation, -1) != desired_org)
        )
        failed_generation_changed = col(cls.failed_global_generation).is_distinct_from(global_generation) | col(
            cls.failed_org_generation
        ).is_distinct_from(desired_org)
        due = col(cls.next_attempt_at).is_(None) | failed_generation_changed | (col(cls.next_attempt_at) <= now)
        query = select(Org.id).outerjoin(cls, col(cls.org_id) == col(Org.id)).where(stale, due).order_by(col(Org.id)).limit(1)
        return (await current_session().execute(query)).scalar_one_or_none()

    @classmethod
    async def try_lock(cls, org_id: UUID) -> bool:
        statement = text("SELECT pg_try_advisory_xact_lock(hashtextextended(CAST(:org_id AS text), 0))")
        return bool((await current_session().execute(statement, {"org_id": str(org_id)})).scalar_one())

    @classmethod
    async def target(cls, org_id: UUID) -> tuple[Self, BundleGenerations]:
        state = await cls.ensure(org_id)
        return state, BundleGenerations(global_=await cls.global_generation(), org=state.desired_generation)

    def is_current(self, generations: BundleGenerations) -> bool:
        return (
            self.current_bundle_id is not None
            and self.published_global_generation == generations.global_
            and self.published_org_generation == generations.org
        )

    async def mark_published(self, bundle_id: UUID, generations: BundleGenerations) -> None:
        self.current_bundle_id = bundle_id
        self.published_global_generation = generations.global_
        self.published_org_generation = generations.org
        self.failed_global_generation = None
        self.failed_org_generation = None
        self.failure_count = 0
        self.next_attempt_at = None
        await self.save()

    @classmethod
    async def record_failure(cls, org_id: UUID, generations: BundleGenerations, now: datetime) -> None:
        from control_plane.models.org import Org  # noqa: PLC0415 bundle state depends on the completed model graph

        organization = (await current_session().execute(select(Org.id).where(Org.id == org_id).with_for_update(key_share=True))).scalar_one_or_none()
        if organization is None:
            return
        state, target = await cls.target(org_id)
        if target != generations or state.is_current(target):
            return
        same_failure = state.failed_global_generation == generations.global_ and state.failed_org_generation == generations.org
        failure_count = state.failure_count + 1 if same_failure else 1
        state.failed_global_generation = generations.global_
        state.failed_org_generation = generations.org
        state.failure_count = failure_count
        state.next_attempt_at = now + timedelta(seconds=min(2 ** (failure_count - 1), 60))
        await state.save()
