from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Self
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import CheckConstraint, Column, Index, Numeric, String, or_, text, tuple_
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Field, col, select

from contract import AuthenticationSource, CostSource, CredentialScope, PrincipalType, TokenUsageSource, UsageStatus, UsdAmount, UsdRate
from contract.model_types import RequestCapability
from contract.money import ZERO_USD
from control_plane.db import current_session
from control_plane.models.common import PageQuery, PageSlice, keyset_page
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut

if TYPE_CHECKING:
    from contract import UsageEvent as UsageEventContract


class UsageEventConflictError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Usage event conflicts with existing evidence")


def _identity(event: UsageEvent | UsageEventContract) -> tuple[UUID, UUID, int | None]:
    return event.org_id, event.request_id, event.attempt_index


def _fact(event: UsageEvent | UsageEventContract) -> dict[str, object]:
    fact = event.model_dump(exclude={"event_id", "schema_version"}, warnings=False)
    fact["requested_capabilities"] = frozenset(event.requested_capabilities)
    return fact


class UsageEvent(Record, table=True):
    __table_args__: ClassVar = (
        CheckConstraint(
            "(status = 'denied' AND token_usage_source = 'not_applicable') OR "
            "(status <> 'denied' AND token_usage_source IN ('provider', 'estimated'))",
            name="usage_event_token_usage_source_valid",
        ),
        CheckConstraint(
            "(authentication_source = 'local' AND principal_type = 'local') OR "
            "(authentication_source IN ('inference_key', 'playground') AND principal_type IN ('human', 'service_account'))",
            name="usage_event_attribution_valid",
        ),
        CheckConstraint(
            "(status = 'denied' AND attempt_index IS NULL AND attempt_started_at IS NULL "
            "AND credential_id IS NULL AND credential_scope IS NULL AND credential_name IS NULL "
            "AND input_price_per_mtok IS NULL AND output_price_per_mtok IS NULL "
            "AND cache_read_price_per_mtok IS NULL AND cache_write_price_per_mtok IS NULL AND cost_source = 'not_applicable') OR "
            "(status <> 'denied' AND attempt_index > 0 AND attempt_started_at IS NOT NULL "
            "AND credential_id IS NOT NULL AND credential_scope IS NOT NULL AND credential_name IS NOT NULL "
            "AND input_price_per_mtok IS NOT NULL AND output_price_per_mtok IS NOT NULL "
            "AND cache_read_price_per_mtok IS NOT NULL AND cache_write_price_per_mtok IS NOT NULL AND cost_source = 'catalog_estimate')",
            name="usage_event_attempt_evidence_valid",
        ),
        CheckConstraint(
            "request_started_at <= occurred_at AND (attempt_started_at IS NULL OR "
            "(request_started_at <= attempt_started_at AND attempt_started_at <= occurred_at))",
            name="usage_event_timestamps_ordered",
        ),
        Index("usage_event_org_occurred_event_idx", "org_id", "occurred_at", "event_id"),
        Index("usage_event_org_workspace_occurred_event_idx", "org_id", "workspace_id", "occurred_at", "event_id"),
        Index("usage_event_org_event_idx", "org_id", "event_id"),
        Index("usage_event_org_workspace_event_idx", "org_id", "workspace_id", "event_id"),
        Index(
            "usage_event_org_request_attempt_key",
            "org_id",
            "request_id",
            "attempt_index",
            unique=True,
            postgresql_where=text("attempt_index IS NOT NULL"),
        ),
        Index(
            "usage_event_org_request_denial_key",
            "org_id",
            "request_id",
            unique=True,
            postgresql_where=text("attempt_index IS NULL"),
        ),
    )

    event_id: UUID = Field(primary_key=True)
    request_id: UUID
    request_started_at: datetime = Field(sa_type=UTCDateTime)
    attempt_started_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    occurred_at: datetime = Field(sa_type=UTCDateTime)
    org_id: UUID
    workspace_id: UUID
    key_id: str
    authentication_source: AuthenticationSource = Field(sa_type=String)
    authentication_label: str
    user_id: UUID
    principal_label: str
    principal_type: PrincipalType = Field(sa_type=String)
    workspace_label: str
    requested_model_id: str
    requested_capabilities: list[RequestCapability] = Field(sa_column=Column(ARRAY(String), nullable=False))
    model_id: str
    provider_id: str
    bundle_id: UUID
    input_tokens: int
    output_tokens: int
    token_usage_source: TokenUsageSource = Field(sa_type=String)
    attempt_index: int | None = None
    max_output_tokens: int | None = None
    input_price_per_mtok: UsdRate | None = Field(default=None, sa_column=Column(Numeric(16, 6), nullable=True))
    output_price_per_mtok: UsdRate | None = Field(default=None, sa_column=Column(Numeric(16, 6), nullable=True))
    cache_read_price_per_mtok: UsdRate | None = Field(default=None, sa_column=Column(Numeric(16, 6), nullable=True))
    cache_write_price_per_mtok: UsdRate | None = Field(default=None, sa_column=Column(Numeric(16, 6), nullable=True))
    cost_source: CostSource = Field(sa_type=String)
    cost_usd: UsdAmount = Field(sa_column=Column(Numeric(28, 12), nullable=False))
    cost_input_usd: UsdAmount = Field(default=ZERO_USD, sa_column=Column(Numeric(28, 12), nullable=False))
    cost_output_usd: UsdAmount = Field(default=ZERO_USD, sa_column=Column(Numeric(28, 12), nullable=False))
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int
    status: UsageStatus = Field(sa_type=String)
    stream: bool
    credential_id: UUID | None = None
    credential_scope: CredentialScope | None = Field(default=None, sa_type=String)
    credential_name: str | None = None

    @classmethod
    async def ingest(cls, events: list[UsageEventContract]) -> list[UUID]:
        by_event_id: dict[UUID, UsageEventContract] = {}
        by_identity: dict[tuple[UUID, UUID, int | None], UsageEventContract] = {}
        for event in events:
            same_event = by_event_id.get(event.event_id)
            same_attempt = by_identity.get(_identity(event))
            if (same_event is not None and _fact(same_event) != _fact(event)) or (same_attempt is not None and _fact(same_attempt) != _fact(event)):
                raise UsageEventConflictError
            by_event_id[event.event_id] = event
            by_identity.setdefault(_identity(event), event)

        candidates = list(by_identity.values())
        values = [event.model_dump(exclude={"schema_version"}) for event in candidates]
        statement = pg_insert(cls).values(values).on_conflict_do_nothing().returning(col(cls.event_id))
        inserted_ids = set((await current_session().execute(statement)).scalars().all())
        pending = [event for event in candidates if event.event_id not in inserted_ids]
        if pending:
            routed = [_identity(event) for event in pending if event.attempt_index is not None]
            denied = [(event.org_id, event.request_id) for event in pending if event.attempt_index is None]
            predicates = [col(cls.event_id).in_([event.event_id for event in pending])]
            if routed:
                predicates.append(tuple_(col(cls.org_id), col(cls.request_id), col(cls.attempt_index)).in_(routed))
            if denied:
                predicates.append(tuple_(col(cls.org_id), col(cls.request_id)).in_(denied) & col(cls.attempt_index).is_(None))
            stored = (await current_session().execute(select(cls).where(or_(*predicates)))).scalars().all()
            stored_by_event_id = {event.event_id: event for event in stored}
            stored_by_identity = {_identity(event): event for event in stored}
            for event in pending:
                existing = stored_by_event_id.get(event.event_id)
                if existing is None:
                    existing = stored_by_identity.get(_identity(event))
                if existing is None or _fact(existing) != _fact(event):
                    raise UsageEventConflictError
        return [event.event_id for event in candidates if event.event_id in inserted_ids]

    @classmethod
    async def for_scope(
        cls,
        org_id: UUID,
        workspace_id: UUID | None,
        page: PageQuery,
    ) -> PageSlice[Self]:
        statement = select(cls).where(cls.org_id == org_id)
        if workspace_id is not None:
            statement = statement.where(cls.workspace_id == workspace_id)
        return await keyset_page(statement, page, col(cls.event_id), UUID)


class UsageEventOut(RecordOut[UsageEvent]):
    event_id: UUID
    request_id: UUID
    request_started_at: datetime
    attempt_started_at: datetime | None
    occurred_at: datetime
    org_id: UUID
    workspace_id: UUID
    key_id: str
    authentication_source: AuthenticationSource
    authentication_label: str
    user_id: UUID
    principal_label: str
    principal_type: PrincipalType
    workspace_label: str
    requested_model_id: str
    requested_capabilities: list[RequestCapability]
    model_id: str
    provider_id: str
    bundle_id: UUID
    input_tokens: int
    output_tokens: int
    token_usage_source: TokenUsageSource = Field(
        description="Token-count provenance: provider, estimated (including partial provider counts), or not_applicable for denials; "
        "independent of cost estimates"
    )
    attempt_index: int | None
    max_output_tokens: int | None
    input_price_per_mtok: UsdRate | None
    output_price_per_mtok: UsdRate | None
    cache_read_price_per_mtok: UsdRate | None
    cache_write_price_per_mtok: UsdRate | None
    cost_source: CostSource
    cost_usd: UsdAmount
    cost_input_usd: UsdAmount
    cost_output_usd: UsdAmount
    cache_read_tokens: int
    cache_write_tokens: int
    latency_ms: int
    status: UsageStatus
    stream: bool
    credential_id: UUID | None
    credential_scope: CredentialScope | None
    credential_name: str | None


class EventsIngestedOut(BaseModel):
    received: int
    ingested: int
