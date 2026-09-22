from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import BigInteger, CheckConstraint, Column, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, col, select

from contract import AuthenticationSource, CostSource, CredentialScope, PrincipalType, TokenUsageSource, UsageStatus, UsdAmount, UsdRate
from contract.model_types import RequestCapability
from control_plane.models.common import PageQuery, PageSlice, keyset_page
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut


class UsageEvent(Record, table=True):
    __table_args__: ClassVar = (
        CheckConstraint(
            "(status = 'denied' AND token_usage_source = 'not_applicable') OR "
            "(status <> 'denied' AND token_usage_source IN ('provider', 'estimated', 'partial', 'unavailable'))",
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
            "AND cache_read_price_per_mtok IS NULL AND cache_write_price_per_mtok IS NULL AND cost_source = 'not_applicable' "
            "AND input_tokens = 0 AND output_tokens = 0 AND cache_read_tokens = 0 AND cache_write_tokens = 0 "
            "AND cost_usd = 0 AND cost_input_usd = 0 AND cost_output_usd = 0) OR "
            "(status <> 'denied' AND attempt_index > 0 AND attempt_started_at IS NOT NULL "
            "AND credential_id IS NOT NULL AND credential_scope IS NOT NULL AND credential_name IS NOT NULL "
            "AND input_price_per_mtok IS NOT NULL AND output_price_per_mtok IS NOT NULL "
            "AND cache_read_price_per_mtok IS NOT NULL AND cache_write_price_per_mtok IS NOT NULL "
            "AND ((token_usage_source = 'unavailable' AND cost_source = 'unavailable' "
            "AND input_tokens IS NULL AND output_tokens IS NULL AND cache_read_tokens IS NULL AND cache_write_tokens IS NULL "
            "AND cost_usd IS NULL AND cost_input_usd IS NULL AND cost_output_usd IS NULL) OR "
            "(token_usage_source IN ('provider', 'estimated', 'partial') AND cost_source = 'catalog_estimate' "
            "AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL AND cache_read_tokens IS NOT NULL AND cache_write_tokens IS NOT NULL "
            "AND input_tokens >= cache_read_tokens + cache_write_tokens "
            "AND cost_usd IS NOT NULL AND cost_input_usd IS NOT NULL AND cost_output_usd IS NOT NULL "
            "AND cost_usd = cost_input_usd + cost_output_usd)))",
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
        Index("usage_event_ingest_id_idx", "ingest_id"),
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
    ingest_id: int = Field(foreign_key="usage_ingest_batch.ingest_id", sa_type=BigInteger)
    request_id: UUID = Field(foreign_key="gateway_request.request_id")
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
    input_tokens: int | None
    output_tokens: int | None
    token_usage_source: TokenUsageSource = Field(sa_type=String)
    attempt_index: int | None = None
    max_output_tokens: int | None = None
    input_price_per_mtok: UsdRate | None = Field(default=None, sa_column=Column(Numeric(16, 6), nullable=True))
    output_price_per_mtok: UsdRate | None = Field(default=None, sa_column=Column(Numeric(16, 6), nullable=True))
    cache_read_price_per_mtok: UsdRate | None = Field(default=None, sa_column=Column(Numeric(16, 6), nullable=True))
    cache_write_price_per_mtok: UsdRate | None = Field(default=None, sa_column=Column(Numeric(16, 6), nullable=True))
    cost_source: CostSource = Field(sa_type=String)
    cost_usd: UsdAmount | None = Field(default=None, sa_column=Column(Numeric(28, 12), nullable=True))
    cost_input_usd: UsdAmount | None = Field(default=None, sa_column=Column(Numeric(28, 12), nullable=True))
    cost_output_usd: UsdAmount | None = Field(default=None, sa_column=Column(Numeric(28, 12), nullable=True))
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    latency_ms: int
    status: UsageStatus = Field(sa_type=String)
    stream: bool
    credential_id: UUID | None = None
    credential_scope: CredentialScope | None = Field(default=None, sa_type=String)
    credential_name: str | None = None

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
    ingest_id: int
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
    input_tokens: int | None
    output_tokens: int | None
    token_usage_source: TokenUsageSource = Field(
        description="Token-count provenance: provider-reported, wholly estimated, partial observation plus estimates, unavailable, "
        "or not_applicable for denials; independent of cost confidence"
    )
    attempt_index: int | None
    max_output_tokens: int | None
    input_price_per_mtok: UsdRate | None
    output_price_per_mtok: UsdRate | None
    cache_read_price_per_mtok: UsdRate | None
    cache_write_price_per_mtok: UsdRate | None
    cost_source: CostSource
    cost_usd: UsdAmount | None
    cost_input_usd: UsdAmount | None
    cost_output_usd: UsdAmount | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    latency_ms: int
    status: UsageStatus
    stream: bool
    credential_id: UUID | None
    credential_scope: CredentialScope | None
    credential_name: str | None


class EventsIngestedOut(BaseModel):
    received: int
    ingested: int
    watermark: UUID | None
