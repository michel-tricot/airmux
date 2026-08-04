from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UsageEventV1(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    event_id: UUID
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
    latency_ms: int
    status: Literal["ok", "upstream_error", "denied", "timeout", "cancelled"]
    stream: bool
