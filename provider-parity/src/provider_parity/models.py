from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

type Transport = Literal["buffered", "streamed"]
type Outcome = Literal["success", "unsupported", "error", "inconclusive"]
type Verdict = Literal[
    "parity",
    "gateway_regression",
    "gateway_only_success",
    "different",
    "inconclusive",
    "expected_difference",
]
type Support = Literal["supported", "unsupported"]
type EgressKind = Literal["openai_compatible", "openai_responses", "anthropic"]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class Requirements(FrozenModel):
    capabilities: frozenset[str] = frozenset()
    input_modalities: frozenset[str] = frozenset()
    parameters: frozenset[str] = frozenset()


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
    tools: tuple[Tool, ...] = ()
    tool_choice: JsonValue | None = None
    parallel_tool_calls: bool | None = None
    response_format: dict[str, JsonValue] | None = None
    reasoning: dict[str, JsonValue] | None = None
    extra: dict[str, JsonValue] = Field(default_factory=dict)


class Oracle(FrozenModel):
    outcome: Outcome = "success"
    text_nonempty: bool = False
    text_contains: str | None = None
    assistant_text: Literal["allowed", "forbidden", "required"] = "allowed"
    tool_names: tuple[str, ...] = ()
    tool_arguments_valid: bool = False
    json_equals: JsonValue | None = None
    reasoning_present: bool = False

    @property
    def has_assertion(self) -> bool:
        return self.outcome != "success" or any(
            (
                self.text_nonempty,
                self.text_contains is not None,
                self.assistant_text != "allowed",
                bool(self.tool_names),
                self.tool_arguments_valid,
                self.json_equals is not None,
                self.reasoning_present,
            )
        )


class Case(FrozenModel):
    version: Literal[1] = 1
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    title: str
    requires: Requirements = Requirements()
    transports: tuple[Transport, ...] = ("buffered",)
    request: Request
    oracle: Oracle

    @model_validator(mode="after")
    def streamed_case_declares_streaming(self) -> Case:
        if "streamed" in self.transports and "streaming" not in self.requires.capabilities:
            return self.model_copy(update={"requires": self.requires.model_copy(update={"capabilities": self.requires.capabilities | {"streaming"}})})
        return self


class Target(FrozenModel):
    provider_id: str
    surface_id: str
    endpoint: str
    egress_kind: EgressKind
    base_url: str
    credential_env: str
    auth: str
    headers: dict[str, str]
    model_id: str
    upstream_model: str
    context_window: int
    max_output_tokens: int | None
    input_modalities: frozenset[str]
    capabilities: frozenset[str]
    parameter_support: dict[str, Support]


class Catalog(FrozenModel):
    targets: tuple[Target, ...]


class Experiment(FrozenModel):
    target: Target
    case: Case
    driver_id: str
    transport: Transport


class Plan(FrozenModel):
    experiments: tuple[Experiment, ...]
    skipped: int = 0

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
    sdk_type: str | None = None


class Comparison(FrozenModel):
    verdict: Verdict
    differences: tuple[str, ...] = ()
    reason: str = ""
    direct_satisfies_oracle: bool | None = None
    gateway_satisfies_oracle: bool | None = None


class PairAttempt(FrozenModel):
    direct: Observation
    gateway: Observation
    comparison: Comparison


class PairResult(FrozenModel):
    case_id: str
    case_version: int = 1
    case_fingerprint: str = ""
    provider_id: str
    surface_id: str
    endpoint: str = ""
    model_id: str
    upstream_model: str = ""
    sdk: str
    transport: Transport
    direct: Observation
    gateway: Observation
    comparison: Comparison
    confirmations: tuple[PairAttempt, ...] = ()


class RunMetadata(FrozenModel):
    run_id: str
    created_at: str
    harness_commit: str
    gateway_url: str
    taxonomy_fingerprint: str
    sdk_versions: dict[str, str]


class ReportDocument(FrozenModel):
    run: RunMetadata
    results: tuple[PairResult, ...]


class ExpectedDifference(FrozenModel):
    provider: str | None = None
    surface: str | None = None
    model: str | None = None
    case: str | None = None
    sdk: str | None = None
    transport: Transport | None = None
    reason: str

    def matches(self, result: PairResult) -> bool:
        values = {
            "provider": result.provider_id,
            "surface": result.surface_id,
            "model": result.model_id,
            "case": result.case_id,
            "sdk": result.sdk,
            "transport": result.transport,
        }
        return all(getattr(self, name) in {None, value} for name, value in values.items())


class ReportPaths(FrozenModel):
    json_path: Path
    html_path: Path
