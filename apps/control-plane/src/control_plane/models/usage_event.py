from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlmodel import Field

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


class EventsIngestedOut(BaseModel):
    received: int
    ingested: int
