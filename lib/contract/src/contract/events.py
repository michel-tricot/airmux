from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

UsageStatus = Literal["ok", "upstream_error", "denied", "timeout", "cancelled", "credential_rejected", "rate_limited"]
"""How a metered request ended.

credential_rejected and rate_limited are split out of upstream_error because they are facts
about the credential rather than about the provider, and the control plane rolls them up into
the credential's status. Everything else upstream stays undifferentiated.
"""
MAX_EVENT_INTEGER = 2_147_483_647


class UsageEventV1(BaseModel):
    """One metered request, emitted by the data plane and ingested by the control plane.

    Delivery is at-least-once from a local disk buffer; the control plane upserts on
    event_id, so replays after an outage land exactly once.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal[1] = 1
    event_id: UUID  # idempotency key for the upsert
    request_id: UUID
    occurred_at: datetime
    org_id: UUID
    workspace_id: UUID  # the workspace of the key that made the request
    key_id: str = Field(min_length=1, max_length=255)
    model_id: str = Field(min_length=1, max_length=255)
    provider_id: str = Field(max_length=63)
    bundle_id: UUID  # which policy version served this request
    input_tokens: int = Field(ge=0, le=MAX_EVENT_INTEGER)
    output_tokens: int = Field(ge=0, le=MAX_EVENT_INTEGER)
    cost_usd: float = Field(ge=0)
    cost_input_usd: float = Field(default=0.0, ge=0)
    cost_output_usd: float = Field(default=0.0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0, le=MAX_EVENT_INTEGER)
    cache_write_tokens: int = Field(default=0, ge=0, le=MAX_EVENT_INTEGER)
    latency_ms: int = Field(ge=0, le=MAX_EVENT_INTEGER)
    status: UsageStatus  # cancelled still carries partial counts
    stream: bool
    credential_id: UUID | None = None  # which provider key paid for this, so spend and health attribute per key
    credential_scope: Literal["platform", "org", "workspace"] | None = None  # separates a tenant's own spend from the platform's

    @field_validator("occurred_at")
    @classmethod
    def require_aware_timestamp(cls, occurred_at: datetime) -> datetime:
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            msg = "occurred_at must include a timezone"
            raise ValueError(msg)
        return occurred_at

    @model_validator(mode="after")
    def require_provider_after_selection(self) -> UsageEventV1:
        if not self.provider_id and self.status != "denied":
            msg = "provider_id is required unless the request was denied before provider selection"
            raise ValueError(msg)
        return self


class HeartbeatV1(BaseModel):
    """A data plane announcing itself to the control plane; the record survives, liveness is derived from last_seen.

    A data plane registers against the instance: which bundle it happens to serve is
    config, and bundle_id already says which one that is.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    instance_id: UUID  # stable per data plane, persisted in its cache dir
    version: str = Field(min_length=1, max_length=100)
    bundle_id: UUID | None = None  # the bundle it is currently serving
