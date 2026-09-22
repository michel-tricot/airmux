from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contract.model_types import AuthenticationSource, PrincipalType, RequestCapability
from contract.money import ZERO_USD, UsdAmount, UsdRate

UsageStatus = Literal["ok", "upstream_error", "denied", "timeout", "cancelled", "credential_rejected", "rate_limited"]
RoutedUsageStatus = Literal["ok", "upstream_error", "timeout", "cancelled", "credential_rejected", "rate_limited"]
CredentialScope = Literal["platform", "org", "workspace"]
CostSource = Literal["catalog_estimate", "unavailable", "not_applicable"]
GatewayRequestOutcome = Literal["succeeded", "failed", "denied", "timeout", "cancelled"]
"""How a metered request ended.

credential_rejected and rate_limited are split out of upstream_error because they are facts
about the credential rather than about the provider, and the control plane rolls them up into
the credential's status. Everything else upstream stays undifferentiated.
"""
MAX_EVENT_INTEGER = 2_147_483_647


class TokenUsageSource(StrEnum):
    PROVIDER = "provider"
    ESTIMATED = "estimated"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class _RequestObservationV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal[1] = Field(1, description="Ingest event schema version")
    event_id: UUID = Field(description="Idempotency key for event ingestion")
    request_id: UUID = Field(description="Data-plane request ID")
    request_started_at: datetime = Field(description="Timestamp when the logical request began")
    occurred_at: datetime = Field(description="Timestamp when this observation completed")
    org_id: UUID = Field(description="Organization that made the request")
    workspace_id: UUID = Field(description="Workspace that made the request")
    key_id: str = Field(description="Inference key ID used for the request", min_length=1, max_length=255)
    authentication_source: AuthenticationSource = Field(description="Credential kind authenticated by the data plane")
    authentication_label: str = Field(description="Credential label at execution time", min_length=1, max_length=200)
    user_id: UUID = Field(description="Authenticated principal for the request")
    principal_label: str = Field(description="Principal label at execution time", min_length=1, max_length=320)
    principal_type: PrincipalType = Field(description="Principal kind at execution time")
    workspace_label: str = Field(description="Workspace label at execution time", min_length=1, max_length=200)
    requested_model_id: str = Field(min_length=1, max_length=255, description="Original caller-requested model before routing and fallback")
    requested_capabilities: frozenset[RequestCapability] = Field(description="Original request capabilities before reconciliation")
    bundle_id: UUID = Field(description="Policy bundle used for the request")
    stream: bool = Field(description="Whether the response was streamed")

    @field_validator("request_started_at", "occurred_at")
    @classmethod
    def require_aware_timestamp(cls, timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            msg = "request observation timestamps must include a timezone"
            raise ValueError(msg)
        return timestamp

    @model_validator(mode="after")
    def valid_request_observation(self) -> Self:
        valid_principal = (
            self.principal_type == "local" if self.authentication_source == "local" else self.principal_type in {"human", "service_account"}
        )
        if not valid_principal:
            msg = "principal_type must match authentication_source"
            raise ValueError(msg)
        if self.request_started_at > self.occurred_at:
            msg = "request_started_at must not follow occurred_at"
            raise ValueError(msg)
        return self


class _UsageEventV1(_RequestObservationV1):
    """One metered provider attempt or policy denial reported by a data plane.

    `event_id` makes retries idempotent.
    """

    event_type: Literal["usage"] = Field(description="Usage-attempt or denial observation")
    model_id: str = Field(description="Caller-facing model ID", min_length=1, max_length=255)
    provider_id: str = Field(description="Provider that served the request, or empty for an early denial", max_length=63)
    input_tokens: int | None = Field(description="Total input tokens when observable", ge=0, le=MAX_EVENT_INTEGER)
    output_tokens: int | None = Field(description="Total output tokens when observable", ge=0, le=MAX_EVENT_INTEGER)
    cost_usd: UsdAmount | None = Field(description="Total catalog-estimated cost when usage is observable")
    cost_input_usd: UsdAmount | None = Field(description="Catalog-estimated input cost when usage is observable")
    cost_output_usd: UsdAmount | None = Field(description="Catalog-estimated output cost when usage is observable")
    max_output_tokens: int | None = Field(description="Effective upstream output-token limit", ge=1, le=MAX_EVENT_INTEGER)
    cache_read_tokens: int | None = Field(description="Input tokens read from a provider cache when observable", ge=0, le=MAX_EVENT_INTEGER)
    cache_write_tokens: int | None = Field(description="Input tokens written to a provider cache when observable", ge=0, le=MAX_EVENT_INTEGER)
    latency_ms: int = Field(ge=0, le=MAX_EVENT_INTEGER)
    status: UsageStatus = Field(description="How the request ended; cancelled events may contain partial token counts")
    credential_id: UUID | None = Field(default=None, description="Provider credential used for the request")
    credential_scope: CredentialScope | None = Field(
        default=None,
        description="Scope of the provider credential used for the request",
    )

    @model_validator(mode="after")
    def exact_total(self) -> Self:
        if (
            self.cost_usd is not None
            and self.cost_input_usd is not None
            and self.cost_output_usd is not None
            and self.cost_usd != self.cost_input_usd + self.cost_output_usd
        ):
            msg = "cost_usd must equal cost_input_usd plus cost_output_usd"
            raise ValueError(msg)
        return self


class DeniedUsageEventV1(_UsageEventV1):
    occurred_at: datetime = Field(description="Timestamp when the request was denied")
    latency_ms: int = Field(description="Request evaluation latency in milliseconds", ge=0, le=MAX_EVENT_INTEGER)
    token_usage_source: Literal[TokenUsageSource.NOT_APPLICABLE] = Field(description="No upstream token usage for a request denied before routing")
    attempt_index: None = Field(None, description="No provider attempt was made")
    attempt_started_at: None = Field(None, description="No provider attempt was made")
    provider_id: Literal[""] = Field("", description="No provider was selected before denial")
    status: Literal["denied"] = Field("denied", description="The request was denied before routing")
    credential_id: None = Field(None, description="No provider credential was selected before denial")
    credential_scope: None = Field(None, description="No provider credential scope was selected before denial")
    credential_name: None = Field(None, description="No provider credential was selected before denial")
    input_price_per_mtok: None = Field(None, description="No provider model was priced")
    output_price_per_mtok: None = Field(None, description="No provider model was priced")
    cache_read_price_per_mtok: None = Field(None, description="No provider model was priced")
    cache_write_price_per_mtok: None = Field(None, description="No provider model was priced")
    cost_source: Literal["not_applicable"] = Field(description="No catalog cost was calculated")

    @model_validator(mode="after")
    def no_usage_or_cost(self) -> Self:
        if any(value != 0 for value in (self.input_tokens, self.output_tokens, self.cache_read_tokens, self.cache_write_tokens)):
            msg = "denied events must have zero tokens"
            raise ValueError(msg)
        if any(value != ZERO_USD for value in (self.cost_usd, self.cost_input_usd, self.cost_output_usd)):
            msg = "denied events must have zero cost"
            raise ValueError(msg)
        return self


class RoutedUsageEventV1(_UsageEventV1):
    attempt_index: int = Field(description="One-based provider attempt order within the logical request", ge=1, le=MAX_EVENT_INTEGER)
    attempt_started_at: datetime = Field(description="Timestamp when this provider attempt began")
    occurred_at: datetime = Field(description="Timestamp when this provider attempt completed")
    latency_ms: int = Field(description="Provider attempt latency in milliseconds", ge=0, le=MAX_EVENT_INTEGER)
    token_usage_source: Literal[
        TokenUsageSource.PROVIDER,
        TokenUsageSource.ESTIMATED,
        TokenUsageSource.PARTIAL,
        TokenUsageSource.UNAVAILABLE,
    ] = Field(description="Whether counts were provider-reported, fully estimated, partially observed, or unavailable")
    provider_id: str = Field(min_length=1, max_length=63, description="Provider that served the request")
    status: RoutedUsageStatus = Field(description="How the routed request ended")
    credential_id: UUID = Field(description="Provider credential used for the request")
    credential_scope: CredentialScope = Field(description="Scope of the provider credential used for the request")
    credential_name: str = Field(description="Provider credential name at execution time", min_length=1, max_length=80)
    input_price_per_mtok: UsdRate = Field(description="Fresh input catalog rate used for this attempt")
    output_price_per_mtok: UsdRate = Field(description="Output catalog rate used for this attempt")
    cache_read_price_per_mtok: UsdRate = Field(description="Cache-read catalog rate used for this attempt")
    cache_write_price_per_mtok: UsdRate = Field(description="Cache-write catalog rate used for this attempt")
    cost_source: Literal["catalog_estimate", "unavailable"] = Field(description="Cost confidence for the attempt")

    @field_validator("attempt_started_at")
    @classmethod
    def require_aware_attempt_timestamp(cls, attempt_started_at: datetime) -> datetime:
        if attempt_started_at.tzinfo is None or attempt_started_at.utcoffset() is None:
            msg = "attempt_started_at must include a timezone"
            raise ValueError(msg)
        return attempt_started_at

    @model_validator(mode="after")
    def ordered_timestamps(self) -> Self:
        if not self.request_started_at <= self.attempt_started_at <= self.occurred_at:
            msg = "request and attempt timestamps must be ordered"
            raise ValueError(msg)
        unavailable_values = (
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.cache_write_tokens,
            self.cost_usd,
            self.cost_input_usd,
            self.cost_output_usd,
        )
        if self.token_usage_source == TokenUsageSource.UNAVAILABLE:
            if any(value is not None for value in unavailable_values) or self.cost_source != "unavailable":
                msg = "unavailable usage requires null tokens and cost"
                raise ValueError(msg)
            return self
        input_tokens = self.input_tokens
        cache_read_tokens = self.cache_read_tokens
        cache_write_tokens = self.cache_write_tokens
        if (
            input_tokens is None
            or self.output_tokens is None
            or cache_read_tokens is None
            or cache_write_tokens is None
            or self.cost_usd is None
            or self.cost_input_usd is None
            or self.cost_output_usd is None
            or self.cost_source != "catalog_estimate"
        ):
            msg = "observable usage requires token counts and catalog-estimated cost"
            raise ValueError(msg)
        if input_tokens < cache_read_tokens + cache_write_tokens:
            msg = "input tokens must include cache-read and cache-write tokens"
            raise ValueError(msg)
        return self


UsageEvent = Annotated[DeniedUsageEventV1 | RoutedUsageEventV1, Field(discriminator="status")]


class GatewayRequestFinishedV1(_RequestObservationV1):
    event_type: Literal["gateway_request_finished"] = Field(description="Terminal logical-request observation")
    outcome: GatewayRequestOutcome = Field(description="Final gateway outcome for the logical request")
    expected_attempts: int = Field(ge=0, le=MAX_EVENT_INTEGER, description="Actual number of routed provider attempts")
    latency_ms: int = Field(ge=0, le=MAX_EVENT_INTEGER, description="End-to-end logical-request latency in milliseconds")

    @model_validator(mode="after")
    def successful_request_was_routed(self) -> Self:
        if self.outcome == "succeeded" and self.expected_attempts == 0:
            message = "a succeeded request requires at least one routed attempt"
            raise ValueError(message)
        return self


IngestEvent = Annotated[UsageEvent | GatewayRequestFinishedV1, Field(discriminator="event_type")]


class HeartbeatV1(BaseModel):
    """The identity, software version, and single active bundle reported by a data plane."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instance_id: UUID = Field(description="Stable ID for this data-plane installation")
    version: str = Field(description="Running data-plane software version", min_length=1, max_length=100)
    bundle_id: UUID | None = Field(default=None, description="Policy bundle served when exactly one is loaded; otherwise absent")
