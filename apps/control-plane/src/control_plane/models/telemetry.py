from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field

from control_plane.models.base import Record


class UsageEvent(Record, table=True):
    event_id: UUID = Field(primary_key=True)
    request_id: str
    occurred_at: datetime
    org_id: str
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


class DataPlaneInstance(Record, table=True):
    instance_id: str = Field(primary_key=True)
    org_id: str | None = None
    version: str
    bundle_id: UUID | None = None
    address: str | None = None
    first_seen: datetime
    last_seen: datetime
