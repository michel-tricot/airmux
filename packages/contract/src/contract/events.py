from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

UsageStatus = Literal["ok", "upstream_error", "denied", "timeout", "cancelled"]


class UsageEventV1(BaseModel):
    """One metered request, emitted by the data plane and ingested by the control plane.

    Delivery is at-least-once from a local disk buffer; the control plane upserts on
    event_id, so replays after an outage land exactly once.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    event_id: UUID  # idempotency key for the upsert
    request_id: UUID
    occurred_at: datetime
    org_id: UUID
    workspace_id: UUID  # the workspace of the key that made the request
    key_id: str
    model_id: str
    provider_id: str
    bundle_id: UUID  # which policy version served this request
    input_tokens: int  # provider-reported where given, tiktoken estimate where not
    output_tokens: int
    cost_usd: float  # cost_input_usd + cost_output_usd, from bundle pricing at request time, never a lookup service
    cost_input_usd: float = 0.0
    cost_output_usd: float = 0.0
    cache_read_tokens: int = 0  # prompt-cache hit tokens, billed at a discount; part of input_tokens
    cache_write_tokens: int = 0
    latency_ms: int
    status: UsageStatus  # cancelled still carries partial counts
    stream: bool


class HeartbeatV1(BaseModel):
    """A data plane announcing itself to the control plane; the record survives, liveness is derived from last_seen."""

    model_config = ConfigDict(frozen=True)

    instance_id: UUID  # stable per data plane, persisted in its cache dir
    version: str
    org_id: UUID | None = None  # which org's bundle it serves
    bundle_id: UUID | None = None  # the bundle it is currently serving
