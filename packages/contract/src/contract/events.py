from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UsageEventV1(BaseModel):
    """One metered request, emitted by the data plane and ingested by the control plane.

    Delivery is at-least-once from a local disk buffer; the control plane upserts on
    event_id, so replays after an outage land exactly once.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    event_id: UUID  # idempotency key for the upsert
    request_id: str
    occurred_at: datetime
    org_id: str
    key_id: str
    model_id: str
    provider_id: str
    bundle_id: UUID  # which policy version served this request
    input_tokens: int  # provider-reported where given, tiktoken estimate where not
    output_tokens: int
    cost_usd: float  # computed from bundle pricing at request time, never from a lookup service
    latency_ms: int
    status: Literal["ok", "upstream_error", "denied", "timeout", "cancelled"]  # cancelled still carries partial counts
    stream: bool
