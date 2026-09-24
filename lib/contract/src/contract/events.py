from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from contract.model_types import RequestCapability
from contract.money import ZERO_USD, UsdAmount

UsageStatus = Literal["ok", "upstream_error", "denied", "timeout", "cancelled", "credential_rejected", "rate_limited"]
RoutedUsageStatus = Literal["ok", "upstream_error", "timeout", "cancelled", "credential_rejected", "rate_limited"]
CredentialScope = Literal["platform", "org", "workspace"]
RequestSource = Literal["inference_key", "playground"]
"""How a metered request ended.

credential_rejected and rate_limited are split out of upstream_error because they are facts
about the credential rather than about the provider, and the control plane rolls them up into
the credential's status. Everything else upstream stays undifferentiated.
"""
MAX_EVENT_INTEGER = 2_147_483_647


class TokenUsageSource(StrEnum):
    PROVIDER = "provider"
    ESTIMATED = "estimated"
    NOT_APPLICABLE = "not_applicable"


class _UsageEventV1(BaseModel):
    """One metered model request reported by a data plane.

    `event_id` makes retries idempotent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal[1] = Field(1, description="Usage event schema version")
    event_id: UUID = Field(description="Idempotency key for event ingestion")
    request_id: UUID = Field(description="Data-plane request ID")
    request_started_at: AwareDatetime = Field(description="Timestamp when the logical request began")
    attempt_started_at: AwareDatetime | None = Field(default=None, description="Timestamp when the provider attempt began")
    occurred_at: AwareDatetime = Field(description="Timestamp when the attempt or denial completed")
    org_id: UUID = Field(description="Organization that made the request")
    workspace_id: UUID = Field(description="Workspace that made the request")
    key_id: str = Field(description="Caller credential ID used for the request", min_length=1, max_length=255)
    request_source: RequestSource = Field(description="Whether the request came from an inference key or a Playground session")
    user_id: UUID = Field(description="Principal that owned the caller credential when the request was made")
    requested_model_id: str = Field(min_length=1, max_length=255, description="Original caller-requested model before routing and fallback")
    requested_capabilities: frozenset[RequestCapability] = Field(description="Original request capabilities before reconciliation")
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
    latency_ms: int = Field(
        description="Gateway latency in milliseconds: per attempt when routed, end-to-end for a denial before routing",
        ge=0,
        le=MAX_EVENT_INTEGER,
    )
    status: UsageStatus = Field(description="How the request ended; cancelled events may contain partial token counts")
    stream: bool = Field(description="Whether the response was streamed")
    credential_id: UUID | None = Field(default=None, description="Provider credential used for the request")
    credential_scope: CredentialScope | None = Field(
        default=None,
        description="Scope of the provider credential used for the request",
    )

    def validate_semantics(self) -> None:
        if self.request_started_at > self.occurred_at or (
            self.attempt_started_at is not None and not self.request_started_at <= self.attempt_started_at <= self.occurred_at
        ):
            message = "request and attempt timestamps must be ordered"
            raise ValueError(message)
        if self.cost_usd != self.cost_input_usd + self.cost_output_usd:
            message = "cost_usd must equal cost_input_usd plus cost_output_usd"
            raise ValueError(message)
        if self.cache_read_tokens + self.cache_write_tokens > self.input_tokens:
            message = "input tokens must include cache-read and cache-write tokens"
            raise ValueError(message)
        if self.status == "denied" and (self.input_tokens != 0 or self.output_tokens != 0 or self.cost_usd != ZERO_USD):
            message = "denied events must have zero tokens and cost"
            raise ValueError(message)


class DeniedUsageEventV1(_UsageEventV1):
    attempt_started_at: None = Field(None, description="No provider attempt was made")
    token_usage_source: Literal[TokenUsageSource.NOT_APPLICABLE] = Field(description="No upstream token usage for a request denied before routing")
    provider_id: Literal[""] = Field("", description="No provider was selected before denial")
    status: Literal["denied"] = Field("denied", description="The request was denied before routing")
    credential_id: None = Field(None, description="No provider credential was selected before denial")
    credential_scope: None = Field(None, description="No provider credential scope was selected before denial")


class RoutedUsageEventV1(_UsageEventV1):
    attempt_started_at: AwareDatetime = Field(description="Timestamp when the provider attempt began")
    token_usage_source: Literal[TokenUsageSource.PROVIDER, TokenUsageSource.ESTIMATED] = Field(
        description="provider: counts accepted from upstream; estimated: gateway estimation was needed, possibly retaining partial provider counts. "
        "Independent of catalog-priced cost estimates"
    )
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
