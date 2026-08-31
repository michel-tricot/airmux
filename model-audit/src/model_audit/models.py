from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_serializer, model_validator

type Transport = Literal["buffered", "streamed"]
type ClientMode = Literal["api", "sdk"]
type Outcome = Literal["success", "rejected", "error", "transient", "inconclusive"]
type FeatureVerdict = Literal["supported", "unsupported", "unknown"]
type FeatureSummary = Literal["supported", "unsupported", "unknown", "mixed"]
type ParityVerdict = Literal["match", "mismatch", "not_evaluated", "inconclusive"]
type ExecutionVerdict = Literal["completed", "transient_failure", "access_blocked", "harness_error"]
type StabilityVerdict = Literal["stable", "flaky"]
type VarianceVerdict = Literal["none", "provider", "gateway", "both", "unknown"]
type ClaimDimension = Literal["capability", "option", "modality", "interaction", "behavior"]
type EvidenceSource = Literal["live_api", "schema", "provider_catalog", "docs"]
type EgressKind = Literal["openai_compatible", "openai_responses", "anthropic"]
type ComparisonDimension = Literal[
    "outcome",
    "text",
    "tool_calls",
    "tool_arguments",
    "finish_reason",
    "usage",
    "reasoning",
    "json",
    "error",
    "adjustments",
]
type FailureKind = Literal["access", "transient", "unsupported", "rejection", "protocol", "provider", "gateway", "unknown"]
type FailureOrigin = Literal["direct", "gateway", "harness", "client", "unknown"]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Applicability(FrozenModel):
    endpoints: frozenset[str] = frozenset()
    egress_kinds: frozenset[EgressKind] = frozenset()
    client_modes: frozenset[ClientMode] = frozenset()

    @field_serializer("endpoints", "egress_kinds", "client_modes")
    def sorted_values(self, values: frozenset[str]) -> list[str]:
        return sorted(values)

    def accepts(self, endpoint: str, egress_kind: EgressKind, client_mode: ClientMode) -> bool:
        return (
            (not self.endpoints or endpoint in self.endpoints)
            and (not self.egress_kinds or egress_kind in self.egress_kinds)
            and (not self.client_modes or client_mode in self.client_modes)
        )


class Tool(FrozenModel):
    name: str
    description: str = ""
    parameters: dict[str, JsonValue]
    strict: bool | None = None


class Request(FrozenModel):
    messages: tuple[dict[str, JsonValue], ...]
    max_tokens: int | None = Field(None, ge=1)
    temperature: float | None = None
    top_p: float | None = None
    stop: tuple[str, ...] | None = None
    seed: int | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = Field(None, ge=0, le=20)
    tools: tuple[Tool, ...] = ()
    tool_choice: JsonValue | None = None
    parallel_tool_calls: bool | None = None
    response_format: dict[str, JsonValue] | None = None
    reasoning: dict[str, JsonValue] | None = None


class Oracle(FrozenModel):
    text_nonempty: bool = False
    text_contains: str | None = None
    text_excludes: str | None = None
    assistant_text: Literal["allowed", "forbidden", "required"] = "allowed"
    tool_names: tuple[str, ...] = ()
    tool_arguments_valid: bool = False
    tool_arguments: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    json_equals: JsonValue | None = None
    reasoning_present: bool = False
    usage_present: bool = False

    @property
    def has_assertion(self) -> bool:
        return any(
            (
                self.text_nonempty,
                self.text_contains is not None,
                self.text_excludes is not None,
                self.assistant_text != "allowed",
                bool(self.tool_names),
                self.tool_arguments_valid,
                bool(self.tool_arguments),
                self.json_equals is not None,
                self.reasoning_present,
                self.usage_present,
            )
        )


class Claim(FrozenModel):
    dimension: ClaimDimension
    name: str = Field(pattern=r"^[a-z][a-z0-9_.+-]+$")
    profile: dict[str, JsonValue] = Field(default_factory=dict)
    assertion: Oracle | None = None

    @property
    def key(self) -> str:
        profile = json.dumps(self.profile, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return f"{self.dimension}:{self.name}:{profile}"


class ComparisonContract(FrozenModel):
    dimensions: frozenset[ComparisonDimension] = frozenset({"outcome", "tool_calls", "tool_arguments", "finish_reason", "error", "adjustments"})

    @field_serializer("dimensions")
    def sorted_dimensions(self, dimensions: frozenset[str]) -> list[str]:
        return sorted(dimensions)


class ExecutionPolicy(FrozenModel):
    max_output_tokens: int = Field(1024, ge=1)


class Case(FrozenModel):
    version: Literal[2] = 2
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    title: str
    claims: tuple[Claim, ...] = Field(min_length=1)
    applies_to: Applicability = Applicability()
    transports: tuple[Transport, ...] = ("buffered",)
    request: Request
    follow_up: Request | None = None
    oracle: Oracle
    comparison: ComparisonContract = ComparisonContract()
    execution: ExecutionPolicy = ExecutionPolicy()

    @property
    def request_count(self) -> int:
        return 1 + int(self.follow_up is not None)

    @property
    def max_output_tokens(self) -> int:
        return self.request.max_tokens or self.execution.max_output_tokens


class Target(FrozenModel):
    provider_id: str
    surface_id: str
    endpoint: str
    egress_kind: EgressKind
    gateway_egress_kind: EgressKind
    base_url: str
    credential_env: str
    auth: str
    headers: dict[str, str]
    param_aliases: dict[str, str]
    model_id: str
    upstream_model: str
    context_window: int
    max_output_tokens: int | None = None


class Catalog(FrozenModel):
    targets: tuple[Target, ...]


class RequestArtifact(FrozenModel):
    surface_id: str
    endpoint: str
    body_fingerprint: str
    semantic_fingerprint: str
    redacted_body: dict[str, JsonValue]


class Experiment(FrozenModel):
    target: Target
    case: Case
    direct_driver_id: str
    gateway_driver_id: str
    gateway_surface_id: str
    gateway_endpoint: str
    transport: Transport
    direct_request: RequestArtifact | None = None
    gateway_request: RequestArtifact | None = None


class Plan(FrozenModel):
    experiments: tuple[Experiment, ...]
    unavailable: int = 0

    @property
    def requests(self) -> int:
        return sum(experiment.case.request_count * 2 for experiment in self.experiments)


class ExperimentReference(FrozenModel):
    target_key: str
    case_id: str
    direct_driver_id: str
    gateway_driver_id: str
    gateway_surface_id: str
    gateway_endpoint: str
    transport: Transport
    direct_request: RequestArtifact | None = None
    gateway_request: RequestArtifact | None = None


class PlanArchive(FrozenModel):
    targets: dict[str, Target]
    cases: dict[str, Case]
    experiments: tuple[ExperimentReference, ...]
    unavailable: int = 0


class ToolObservation(FrozenModel):
    id: str | None = None
    name: str
    arguments: str

    @property
    def valid_arguments(self) -> bool:
        try:
            return isinstance(json.loads(self.arguments), dict)
        except json.JSONDecodeError:
            return False

    @property
    def parsed_arguments(self) -> dict[str, JsonValue] | None:
        try:
            value = json.loads(self.arguments)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None


class Failure(FrozenModel):
    kind: FailureKind
    origin: FailureOrigin = "unknown"
    subject: str | None = None
    retryable: bool = False
    code: str | None = None
    message: str = ""
    http_status: int | None = None


class UsageObservation(FrozenModel):
    source: Literal["reported", "estimated"] = "reported"
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ReasoningObservation(FrozenModel):
    exposed: bool
    kind: str | None = None
    signature_present: bool = False


class Observation(FrozenModel):
    outcome: Outcome
    text: str = ""
    tool_calls: tuple[ToolObservation, ...] = ()
    finish_reason: str | None = None
    usage_present: bool = False
    reasoning_present: bool = False
    json_value: JsonValue | None = None
    error_code: str | None = None
    error_message: str | None = None
    http_status: int | None = None
    adjustments: tuple[str, ...] = ()
    duration_ms: float = 0
    client_type: str | None = None
    failure: Failure | None = None
    usage: UsageObservation | None = None
    reasoning: ReasoningObservation | None = None

    @model_validator(mode="after")
    def include_failure(self) -> Observation:
        if self.usage is not None and not self.usage_present:
            object.__setattr__(self, "usage_present", True)
        if self.usage_present and self.usage is None:
            object.__setattr__(self, "usage", UsageObservation())
        if self.reasoning is not None and not self.reasoning_present:
            object.__setattr__(self, "reasoning_present", self.reasoning.exposed)
        if self.reasoning_present and self.reasoning is None:
            object.__setattr__(self, "reasoning", ReasoningObservation(exposed=True))
        if self.outcome != "success" and self.failure is None:
            if self.outcome == "inconclusive":
                kind: FailureKind = "access"
            elif self.outcome == "transient":
                kind = "transient"
            elif self.outcome == "rejected":
                kind = "rejection"
            else:
                kind = "unknown"
            failure = Failure(
                kind=kind,
                retryable=self.outcome == "transient",
                code=self.error_code,
                message=self.error_message or "",
                http_status=self.http_status,
            )
            object.__setattr__(self, "failure", failure)
        return self

    @property
    def retryable(self) -> bool:
        return self.outcome == "transient" or (self.failure is not None and self.failure.retryable)


class Difference(FrozenModel):
    code: str
    direct: JsonValue = None
    gateway: JsonValue = None


class ClaimAssessment(FrozenModel):
    claim: Claim
    feature: FeatureVerdict
    direct_satisfies: bool | None = None
    gateway_satisfies: bool | None = None


class Assessment(FrozenModel):
    execution: ExecutionVerdict
    stability: StabilityVerdict = "stable"
    variance: VarianceVerdict = "none"
    feature: FeatureSummary
    parity: ParityVerdict
    differences: tuple[Difference, ...] = ()
    claims: tuple[ClaimAssessment, ...] = ()
    reason: str = ""
    direct_satisfies_oracle: bool | None = None
    gateway_satisfies_oracle: bool | None = None

    @property
    def difference_codes(self) -> tuple[str, ...]:
        return tuple(difference.code for difference in self.differences)


class PairAttempt(FrozenModel):
    direct: Observation
    gateway: Observation
    assessment: Assessment


class PairResult(FrozenModel):
    case_id: str
    case_version: int
    case_fingerprint: str
    claims: tuple[Claim, ...]
    provider_id: str
    surface_id: str
    endpoint: str
    gateway_surface_id: str
    gateway_endpoint: str
    model_id: str
    upstream_model: str
    client: str
    transport: Transport
    direct: Observation
    gateway: Observation
    assessment: Assessment
    attempts: tuple[PairAttempt, ...] = ()
    direct_request: RequestArtifact | None = None
    gateway_request: RequestArtifact | None = None


class RunMetadata(FrozenModel):
    run_id: str
    created_at: str
    harness_commit: str
    harness_fingerprint: str
    gateway_url: str
    taxonomy_fingerprint: str
    client_versions: dict[str, str]


class RunSettings(FrozenModel):
    confirmations: int = 1
    transient_retries: int = 2
    retry_backoff_seconds: float = 2
    request_timeout_seconds: float = 60


class ReportDocument(FrozenModel):
    schema_version: Literal[7] = 7
    run: RunMetadata
    plan: PlanArchive | None = None
    settings: RunSettings = RunSettings()
    complete: bool = True
    results: tuple[PairResult, ...]


class EvidenceRecord(FrozenModel):
    schema_version: Literal[2] = 2
    evidence_id: str
    provider_id: str
    model_id: str
    upstream_model: str
    surface_id: str
    endpoint: str
    case_id: str
    case_version: int
    case_fingerprint: str
    claim: Claim
    verdict: FeatureVerdict
    source: EvidenceSource = "live_api"
    observation: Observation
    attempts: int
    observed_at: str
    harness_commit: str
    harness_fingerprint: str
    taxonomy_fingerprint: str


class BehaviorRecord(FrozenModel):
    provider_id: str
    model_id: str
    surface_id: str
    endpoint: str
    claim: Claim
    verdict: FeatureVerdict
    evidence_ids: tuple[str, ...]
    observed_at: str


class EvidenceLedger(FrozenModel):
    schema_version: Literal[2] = 2
    records: tuple[EvidenceRecord, ...] = ()


class BehaviorTaxonomy(FrozenModel):
    schema_version: Literal[2] = 2
    generated_from: str
    behaviors: tuple[BehaviorRecord, ...]


class ReportPaths(FrozenModel):
    json_path: Path
    html_path: Path
