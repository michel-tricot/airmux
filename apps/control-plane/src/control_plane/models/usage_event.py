from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import CheckConstraint, Column, Index, Numeric, String
from sqlmodel import Field, col, select

from contract import CredentialScope, TokenUsageSource, UsageStatus, UsdAmount
from contract.money import ZERO_USD
from control_plane.models.common import PageQuery, PageSlice, keyset_page
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut


class UsageEvent(Record, table=True):
    __table_args__: ClassVar = (
        CheckConstraint(
            "(status = 'denied' AND token_usage_source = 'not_applicable') OR "
            "(status <> 'denied' AND token_usage_source IN ('provider', 'estimated'))",
            name="usage_event_token_usage_source_valid",
        ),
        Index("usage_event_org_occurred_event_idx", "org_id", "occurred_at", "event_id"),
        Index("usage_event_org_workspace_occurred_event_idx", "org_id", "workspace_id", "occurred_at", "event_id"),
        Index("usage_event_org_event_idx", "org_id", "event_id"),
        Index("usage_event_org_workspace_event_idx", "org_id", "workspace_id", "event_id"),
    )

    event_id: UUID = Field(primary_key=True)
    request_id: UUID
    occurred_at: datetime = Field(sa_type=UTCDateTime)
    org_id: UUID
    workspace_id: UUID
    key_id: str
    model_id: str
    provider_id: str
    bundle_id: UUID
    input_tokens: int
    output_tokens: int
    token_usage_source: TokenUsageSource = Field(sa_type=String)
    max_output_tokens: int | None = None
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
        return await keyset_page(
            statement,
            page,
            col(cls.event_id),
            UUID,
        )


class UsageEventOut(RecordOut[UsageEvent]):
    event_id: UUID
    request_id: UUID
    occurred_at: datetime
    org_id: UUID
    workspace_id: UUID
    key_id: str
    model_id: str
    provider_id: str
    bundle_id: UUID
    input_tokens: int
    output_tokens: int
    token_usage_source: TokenUsageSource = Field(
        description="Token-count provenance: provider, estimated (including partial provider counts), or not_applicable for denials; "
        "independent of cost estimates"
    )
    max_output_tokens: int | None
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


class EventsIngestedOut(BaseModel):
    received: int
    ingested: int
