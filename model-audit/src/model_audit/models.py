from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field

type Transport = Literal["buffered", "streamed"]
type ClientMode = Literal["api", "sdk"]
type Outcome = Literal["success", "rejected", "error", "transient", "inconclusive"]
type FeatureVerdict = Literal["supported", "unsupported", "unknown"]
type ParityVerdict = Literal["match", "mismatch", "not_evaluated", "inconclusive"]
type ExecutionVerdict = Literal["completed", "transient_failure", "access_blocked", "harness_error"]
type ClaimDimension = Literal["capability", "option", "modality", "interaction", "behavior"]
type EvidenceSource = Literal["live_api", "schema", "provider_catalog", "docs"]
type EgressKind = Literal["openai_compatible", "openai_responses", "anthropic"]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class Claim(FrozenModel):
    dimension: ClaimDimension
    name: str = Field(pattern=r"^[a-z][a-z0-9_.+-]+$")
    profile: dict[str, JsonValue] = Field(default_factory=dict)

    @computed_field
    @property
    def key(self) -> str:
        profile = json.dumps(self.profile, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return f"{self.dimension}:{self.name}:{profile}"


class Applicability(FrozenModel):
    endpoints: frozenset[str] = frozenset()
    egress_kinds: frozenset[EgressKind] = frozenset()
    client_modes: frozenset[ClientMode] = frozenset()

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
    max_tokens: int = Field(1024, ge=1)
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
    extra: dict[str, JsonValue] = Field(default_factory=dict)


class Oracle(FrozenModel):
    text_nonempty: bool = False
    text_contains: str | None = None
    text_excludes: str | None = None
    assistant_text: Literal["allowed", "forbidden", "required"] = "allowed"
    tool_names: tuple[str, ...] = ()
    tool_arguments_valid: bool = False
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
                self.json_equals is not None,
                self.reasoning_present,
                self.usage_present,
            )
        )


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
    model_id: str
    upstream_model: str
    context_window: int
    max_output_tokens: int | None = None


class Catalog(FrozenModel):
    targets: tuple[Target, ...]


class Experiment(FrozenModel):
    target: Target
    case: Case
    direct_driver_id: str
    gateway_driver_id: str
    gateway_surface_id: str
    gateway_endpoint: str
    transport: Transport


class Plan(FrozenModel):
    experiments: tuple[Experiment, ...]
    unavailable: int = 0

    @property
    def requests(self) -> int:
        return len(self.experiments) * 2


class ToolObservation(FrozenModel):
    name: str
    arguments: str

    @property
    def valid_arguments(self) -> bool:
        try:
            return isinstance(json.loads(self.arguments), dict)
        except json.JSONDecodeError:
            return False


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


class Assessment(FrozenModel):
    execution: ExecutionVerdict
    feature: FeatureVerdict
    parity: ParityVerdict
    differences: tuple[str, ...] = ()
    reason: str = ""
    direct_satisfies_oracle: bool | None = None
    gateway_satisfies_oracle: bool | None = None


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


class RunMetadata(FrozenModel):
    run_id: str
    created_at: str
    harness_commit: str
    gateway_url: str
    taxonomy_fingerprint: str
    client_versions: dict[str, str]


class RunSettings(FrozenModel):
    confirmations: int = 1
    transient_retries: int = 2
    retry_backoff_seconds: float = 2
    request_timeout_seconds: float = 60


class ReportDocument(FrozenModel):
    schema_version: Literal[4] = 4
    run: RunMetadata
    plan: Plan | None = None
    settings: RunSettings = RunSettings()
    complete: bool = True
    results: tuple[PairResult, ...]


class EvidenceRecord(FrozenModel):
    schema_version: Literal[1] = 1
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
    schema_version: Literal[1] = 1
    records: tuple[EvidenceRecord, ...] = ()


class BehaviorTaxonomy(FrozenModel):
    schema_version: Literal[1] = 1
    generated_from: str
    behaviors: tuple[BehaviorRecord, ...]


class ReportPaths(FrozenModel):
    json_path: Path
    html_path: Path
