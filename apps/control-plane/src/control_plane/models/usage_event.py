from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, model_validator
from pydantic import Field as PydanticField
from sqlalchemy import Column, Index, Numeric, String, and_, or_
from sqlmodel import Field, col

from contract import CredentialScope, UsageStatus, UsdAmount
from contract.money import ZERO_USD
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut, RequestModel


class UsageEvent(Record, table=True):
    __table_args__: ClassVar = (
        Index("usage_event_org_occurred_event_idx", "org_id", "occurred_at", "event_id"),
        Index("usage_event_org_workspace_occurred_event_idx", "org_id", "workspace_id", "occurred_at", "event_id"),
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
        page: UsageEventPage,
    ) -> list[Self]:
        occurred_at = col(cls.occurred_at)
        event_id = col(cls.event_id)
        if page.before is not None and page.before_event_id is not None:
            cursor = (or_(occurred_at < page.before, and_(occurred_at == page.before, event_id < page.before_event_id)),)
            order = (occurred_at.desc(), event_id.desc())
        elif page.after is not None and page.after_event_id is not None:
            cursor = (or_(occurred_at > page.after, and_(occurred_at == page.after, event_id > page.after_event_id)),)
            order = (occurred_at.asc(), event_id.asc())
        else:
            cursor = ()
            order = (occurred_at.desc(), event_id.desc())
        workspace_condition = (cls.workspace_id == workspace_id,) if workspace_id is not None else ()
        return await cls.find(
            cls.org_id == org_id,
            *workspace_condition,
            *cursor,
            order_by=order,
            limit=page.limit,
        )


class UsageEventPage(RequestModel):
    before: datetime | None = None
    before_event_id: UUID | None = None
    after: datetime | None = None
    after_event_id: UUID | None = None
    limit: int = PydanticField(default=50, ge=1, le=200)

    @model_validator(mode="after")
    def validate_cursor(self) -> Self:
        if (self.before is None) != (self.before_event_id is None):
            msg = "before and before_event_id must be supplied together"
            raise ValueError(msg)
        if (self.after is None) != (self.after_event_id is None):
            msg = "after and after_event_id must be supplied together"
            raise ValueError(msg)
        if self.before is not None and self.after is not None:
            msg = "supply either a before cursor or an after cursor, not both"
            raise ValueError(msg)
        for name, cursor in (("before", self.before), ("after", self.after)):
            if cursor is not None and (cursor.tzinfo is None or cursor.utcoffset() is None):
                msg = f"{name} must include a timezone"
                raise ValueError(msg)
        return self


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
