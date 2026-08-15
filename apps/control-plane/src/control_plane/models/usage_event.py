from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel
from sqlmodel import Field, col

from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut


class UsageEvent(Record, table=True):
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
    cost_usd: float
    cost_input_usd: float = 0.0
    cost_output_usd: float = 0.0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int
    status: str
    stream: bool
    credential_id: UUID | None = None
    credential_scope: str | None = None

    @classmethod
    async def for_org(
        cls,
        org_id: UUID,
        *,
        after: datetime | None,
        workspace_id: UUID | None,
        limit: int,
    ) -> list[Self]:
        occurred_at = col(cls.occurred_at)
        after_condition = (occurred_at > after,) if after is not None else ()
        workspace_condition = (cls.workspace_id == workspace_id,) if workspace_id is not None else ()
        order = occurred_at.asc() if after is not None else occurred_at.desc()
        return await cls.find(cls.org_id == org_id, *workspace_condition, *after_condition, order_by=order, limit=limit)


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
    cost_usd: float
    cost_input_usd: float
    cost_output_usd: float
    cache_read_tokens: int
    cache_write_tokens: int
    latency_ms: int
    status: str
    stream: bool
    credential_id: UUID | None
    credential_scope: str | None


class EventsIngestedOut(BaseModel):
    received: int
    ingested: int
