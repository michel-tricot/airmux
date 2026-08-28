from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from model_audit.models import Assessment, Observation, PairResult


@dataclass(frozen=True)
class DifferenceDetail:
    label: str
    direct: str
    gateway: str


LABELS = {
    "outcome": "Outcome",
    "tool_calls": "Tool calls",
    "tool_arguments": "Tool arguments",
    "finish_reason": "Finish reason",
    "usage_presence": "Usage",
    "reasoning_presence": "Reasoning",
    "json": "JSON",
    "error_category": "Error category",
    "adjustments": "Adjustments",
    "oracle": "Case oracle",
}


def _text(value: str, limit: int = 120) -> str:
    collapsed = " ".join(value.split())
    return collapsed if len(collapsed) <= limit else f"{collapsed[: limit - 1]}…"


def observation_summary(observation: Observation) -> str:
    calls = ",".join(call.name for call in observation.tool_calls) or "none"
    error = observation.error_code or "none"
    message = _text(observation.error_message or "")
    return (
        f'{observation.outcome}; text="{_text(observation.text)}"; tools={calls}; usage={"yes" if observation.usage_present else "no"}; '
        f'reasoning={"yes" if observation.reasoning_present else "no"}; error={error}; http={observation.http_status or "none"}; message="{message}"'
    )


def parity_display(assessment: Assessment) -> str:
    return {
        "match": "✓ match",
        "mismatch": "✗ mismatch",
        "not_evaluated": "↻ not evaluated",
        "inconclusive": "? inconclusive",
    }[assessment.parity]


def feature_display(assessment: Assessment) -> str:
    return {"supported": "✓ supported", "unsupported": "○ unsupported", "unknown": "? unknown"}[assessment.feature]


def stability_display(assessment: Assessment) -> str:
    return {"stable": "stable", "flaky": "~ flaky"}[assessment.stability]


def execution_display(assessment: Assessment) -> str:
    return {
        "completed": "✓ completed",
        "transient_failure": "↻ transient failure",
        "access_blocked": "? access blocked",
        "harness_error": "✗ harness error",
    }[assessment.execution]


def validation_failed(result: PairResult) -> bool:
    return result.assessment.parity == "mismatch" or result.assessment.execution == "harness_error"


def gap_kind(result: PairResult) -> str:
    assessment = result.assessment
    if assessment.execution == "harness_error":
        kind = "harness"
    elif assessment.execution == "transient_failure":
        kind = "transient"
    elif assessment.parity == "inconclusive":
        kind = "inconclusive"
    elif assessment.parity == "match":
        kind = "flaky" if assessment.stability == "flaky" else "none"
    elif assessment.parity == "not_evaluated" and assessment.stability == "flaky":
        kind = "flaky"
    elif assessment.feature == "supported" and result.gateway.outcome != "success":
        kind = "gateway_rejection"
    elif "oracle" in assessment.differences:
        kind = "semantic"
    elif "error_category" in assessment.differences:
        kind = "error_mapping"
    elif result.transport == "streamed":
        kind = "streaming"
    else:
        kind = "translation"
    return kind


def difference_details(result: PairResult) -> tuple[DifferenceDetail, ...]:
    direct = result.direct
    gateway = result.gateway
    values = {
        "outcome": (direct.outcome, gateway.outcome),
        "tool_calls": (", ".join(call.name for call in direct.tool_calls) or "none", ", ".join(call.name for call in gateway.tool_calls) or "none"),
        "tool_arguments": (
            "; ".join(f"{call.name}={_text(call.arguments)}" for call in direct.tool_calls) or "none",
            "; ".join(f"{call.name}={_text(call.arguments)}" for call in gateway.tool_calls) or "none",
        ),
        "finish_reason": (direct.finish_reason or "none", gateway.finish_reason or "none"),
        "usage_presence": ("present" if direct.usage_present else "absent", "present" if gateway.usage_present else "absent"),
        "reasoning_presence": ("present" if direct.reasoning_present else "absent", "present" if gateway.reasoning_present else "absent"),
        "json": (json.dumps(direct.json_value, sort_keys=True), json.dumps(gateway.json_value, sort_keys=True)),
        "error_category": (direct.error_code or direct.outcome, gateway.error_code or gateway.outcome),
        "adjustments": (", ".join(direct.adjustments) or "none", ", ".join(gateway.adjustments) or "none"),
        "oracle": (
            str(result.assessment.direct_satisfies_oracle),
            str(result.assessment.gateway_satisfies_oracle),
        ),
    }
    return tuple(DifferenceDetail(LABELS[name], *values[name]) for name in result.assessment.differences)
