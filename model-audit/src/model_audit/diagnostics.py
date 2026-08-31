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
    "usage": "Usage",
    "reasoning": "Reasoning",
    "json": "JSON",
    "error": "Error category",
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
    usage = "no"
    if observation.usage is not None:
        input_tokens = "?" if observation.usage.input_tokens is None else str(observation.usage.input_tokens)
        output_tokens = "?" if observation.usage.output_tokens is None else str(observation.usage.output_tokens)
        total_tokens = "?" if observation.usage.total_tokens is None else str(observation.usage.total_tokens)
        usage = f"{input_tokens} in/{output_tokens} out/{total_tokens} total"
    reasoning = (observation.reasoning.kind or "yes") if observation.reasoning is not None else "no"
    return (
        f'{observation.outcome}; text="{_text(observation.text)}"; tools={calls}; usage={usage}; reasoning={reasoning}; '
        f'error={error}; http={observation.http_status or "none"}; message="{message}"'
    )


def parity_display(assessment: Assessment) -> str:
    return {
        "match": "✓ match",
        "mismatch": "✗ mismatch",
        "not_evaluated": "↻ not evaluated",
        "inconclusive": "? inconclusive",
    }[assessment.parity]


def feature_display(assessment: Assessment) -> str:
    return {"supported": "✓ supported", "unsupported": "○ unsupported", "unknown": "? unknown", "mixed": "~ mixed"}[assessment.feature]


def stability_display(assessment: Assessment) -> str:
    return "stable" if assessment.stability == "stable" else f"~ flaky ({assessment.variance} variance)"


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
    elif assessment.variance in {"provider", "both"}:
        kind = "provider_variance"
    elif assessment.parity == "match":
        kind = "flaky" if assessment.stability == "flaky" else "none"
    elif assessment.parity == "not_evaluated" and assessment.stability == "flaky":
        kind = "flaky"
    elif assessment.feature == "supported" and result.gateway.outcome != "success":
        kind = "gateway_rejection"
    elif "oracle" in assessment.difference_codes:
        kind = "semantic"
    elif "error" in assessment.difference_codes:
        kind = "error_mapping"
    elif result.transport == "streamed":
        kind = "streaming"
    else:
        kind = "translation"
    return kind


def difference_details(result: PairResult) -> tuple[DifferenceDetail, ...]:
    def display(value: object) -> str:
        if isinstance(value, str):
            return _text(value)
        return _text(json.dumps(value, sort_keys=True, ensure_ascii=False))

    return tuple(
        DifferenceDetail(
            LABELS.get(difference.code, difference.code.replace("_", " ").title()), display(difference.direct), display(difference.gateway)
        )
        for difference in result.assessment.differences
    )
