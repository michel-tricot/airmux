from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from provider_parity.models import Comparison, Observation, PairResult


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
    "error_code": "Error code",
    "oracle": "Case oracle",
}


def _text(value: str, limit: int = 120) -> str:
    collapsed = " ".join(value.split())
    return collapsed if len(collapsed) <= limit else f"{collapsed[: limit - 1]}…"


def _value(name: str, observation: Observation, satisfies_oracle: bool | None) -> str:
    values = {
        "outcome": observation.outcome,
        "tool_calls": ", ".join(call.name for call in observation.tool_calls) or "none",
        "tool_arguments": "; ".join(f"{call.name}={_text(call.arguments)}" for call in observation.tool_calls) or "none",
        "finish_reason": observation.finish_reason or "none",
        "usage_presence": "present" if observation.usage_present else "absent",
        "reasoning_presence": "present" if observation.reasoning_present else "absent",
        "json": _text(json.dumps(observation.json_value, sort_keys=True, ensure_ascii=False)),
        "error_code": observation.error_code or "none",
        "oracle": "satisfied" if satisfies_oracle else "not satisfied" if satisfies_oracle is False else "not evaluated",
    }
    return values.get(name, "unknown")


def difference_details(result: PairResult) -> tuple[DifferenceDetail, ...]:
    comparison = result.comparison
    return tuple(
        DifferenceDetail(
            label=LABELS.get(name, name.replace("_", " ").title()),
            direct=_value(name, result.direct, comparison.direct_satisfies_oracle),
            gateway=_value(name, result.gateway, comparison.gateway_satisfies_oracle),
        )
        for name in comparison.differences
    )


def case_result(comparison: Comparison) -> str:
    direct = comparison.direct_satisfies_oracle
    gateway = comparison.gateway_satisfies_oracle
    if direct is None or gateway is None:
        return "not evaluated"
    if direct and gateway:
        return "passed"
    if not direct and not gateway:
        return "failed both"
    return "failed gateway" if direct else "failed direct"


def observation_summary(observation: Observation) -> str:
    values = [observation.outcome, f'text="{_text(observation.text)}"']
    if observation.tool_calls:
        values.append(f"tools={','.join(call.name for call in observation.tool_calls)}")
    if observation.finish_reason is not None:
        values.append(f"finish={observation.finish_reason}")
    values.extend((f"usage={'yes' if observation.usage_present else 'no'}", f"reasoning={'yes' if observation.reasoning_present else 'no'}"))
    if observation.error_code is not None:
        values.append(f"error={observation.error_code}")
    if observation.error_message:
        values.append(f'message="{_text(observation.error_message)}"')
    if observation.adjustments:
        values.append(f"adjustments={','.join(observation.adjustments)}")
    return "; ".join(values)
