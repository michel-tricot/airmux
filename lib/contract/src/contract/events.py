from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contract.money import ZERO_USD, UsdAmount

UsageStatus = Literal["ok", "upstream_error", "denied", "timeout", "cancelled", "credential_rejected", "rate_limited"]
RoutedUsageStatus = Literal["ok", "upstream_error", "timeout", "cancelled", "credential_rejected", "rate_limited"]
CredentialScope = Literal["platform", "org", "workspace"]
"""How a metered request ended.

credential_rejected and rate_limited are split out of upstream_error because they are facts
about the credential rather than about the provider, and the control plane rolls them up into
the credential's status. Everything else upstream stays undifferentiated.
"""
MAX_EVENT_INTEGER = 2_147_483_647


class _UsageEventV1(BaseModel):
    """One metered model request reported by a data plane.

    `event_id` makes retries idempotent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal[1] = Field(1, description="Usage event schema version")
    event_id: UUID = Field(description="Idempotency key for event ingestion")
    request_id: UUID = Field(description="Data-plane request ID")
    occurred_at: datetime = Field(description="Timestamp when the request completed")
    org_id: UUID = Field(description="Organization that made the request")
    workspace_id: UUID = Field(description="Workspace that made the request")
    key_id: str = Field(description="Inference key ID used for the request", min_length=1, max_length=255)
    model_id: str = Field(description="Caller-facing model ID", min_length=1, max_length=255)
    provider_id: str = Field(description="Provider that served the request, or empty for an early denial", max_length=63)
    bundle_id: UUID = Field(description="Policy bundle used for the request")
    input_tokens: int = Field(description="Total input tokens", ge=0, le=MAX_EVENT_INTEGER)
    output_tokens: int = Field(description="Total output tokens", ge=0, le=MAX_EVENT_INTEGER)
    cost_usd: UsdAmount = Field(description="Total estimated cost in USD")
    cost_input_usd: UsdAmount = Field(default=ZERO_USD, description="Estimated input cost in USD")
    cost_output_usd: UsdAmount = Field(default=ZERO_USD, description="Estimated output cost in USD")
    max_output_tokens: int | None = Field(description="Effective upstream output-token limit", ge=1, le=MAX_EVENT_INTEGER)
    cache_read_tokens: int = Field(default=0, description="Input tokens read from a provider cache", ge=0, le=MAX_EVENT_INTEGER)
    cache_write_tokens: int = Field(default=0, description="Input tokens written to a provider cache", ge=0, le=MAX_EVENT_INTEGER)
    latency_ms: int = Field(description="End-to-end request latency in milliseconds", ge=0, le=MAX_EVENT_INTEGER)
    status: UsageStatus = Field(description="How the request ended; cancelled events may contain partial token counts")
    stream: bool = Field(description="Whether the response was streamed")
    credential_id: UUID | None = Field(default=None, description="Provider credential used for the request")
    credential_scope: CredentialScope | None = Field(
        default=None,
        description="Scope of the provider credential used for the request",
    )

    @field_validator("occurred_at")
    @classmethod
    def require_aware_timestamp(cls, occurred_at: datetime) -> datetime:
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            msg = "occurred_at must include a timezone"
            raise ValueError(msg)
        return occurred_at

    @model_validator(mode="after")
    def exact_total(self) -> Self:
        if self.cost_usd != self.cost_input_usd + self.cost_output_usd:
            msg = "cost_usd must equal cost_input_usd plus cost_output_usd"
            raise ValueError(msg)
        if self.status == "denied" and self.cost_usd != ZERO_USD:
            msg = "denied events must have zero cost"
            raise ValueError(msg)
        return self


class DeniedUsageEventV1(_UsageEventV1):
    provider_id: Literal[""] = Field("", description="No provider was selected before denial")
    status: Literal["denied"] = Field("denied", description="The request was denied before routing")
    credential_id: None = Field(None, description="No provider credential was selected before denial")
    credential_scope: None = Field(None, description="No provider credential scope was selected before denial")


class RoutedUsageEventV1(_UsageEventV1):
    provider_id: str = Field(min_length=1, max_length=63, description="Provider that served the request")
    status: RoutedUsageStatus = Field(description="How the routed request ended")
    credential_id: UUID = Field(description="Provider credential used for the request")
    credential_scope: CredentialScope = Field(description="Scope of the provider credential used for the request")


UsageEvent = Annotated[DeniedUsageEventV1 | RoutedUsageEventV1, Field(discriminator="status")]


class HeartbeatV1(BaseModel):
    """The identity, software version, and single active bundle reported by a data plane."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instance_id: UUID = Field(description="Stable ID for this data-plane installation")
    version: str = Field(description="Running data-plane software version", min_length=1, max_length=100)
    bundle_id: UUID | None = Field(default=None, description="Policy bundle served when exactly one is loaded; otherwise absent")
