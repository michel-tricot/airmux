from __future__ import annotations

import json

from provider_parity.models import Comparison, Observation, Oracle


def _finish_class(reason: str | None) -> str | None:
    return {
        "end_turn": "stop",
        "stop": "stop",
        "tool_use": "tools",
        "tool_calls": "tools",
        "length": "length",
        "max_tokens": "length",
    }.get(reason, reason)


def satisfies(observation: Observation, oracle: Oracle) -> bool:
    if observation.outcome != oracle.outcome:
        return False
    if observation.outcome != "success":
        return True
    names = tuple(sorted(tool.name for tool in observation.tool_calls))
    expected_names = tuple(sorted(oracle.tool_names))
    assertions = (
        not oracle.text_nonempty or bool(observation.text.strip()),
        oracle.text_contains is None or oracle.text_contains.casefold() in observation.text.casefold(),
        oracle.assistant_text != "forbidden" or not observation.text.strip(),
        oracle.assistant_text != "required" or bool(observation.text.strip()),
        not oracle.tool_names or names == expected_names,
        not oracle.tool_arguments_valid or all(tool.valid_arguments for tool in observation.tool_calls),
        oracle.json_equals is None or observation.json_value == oracle.json_equals,
        not oracle.reasoning_present or observation.reasoning_present,
    )
    return all(assertions)


def _differences(direct: Observation, gateway: Observation) -> tuple[str, ...]:
    values = {
        "outcome": (direct.outcome, gateway.outcome),
        "tool_calls": (tuple(sorted(tool.name for tool in direct.tool_calls)), tuple(sorted(tool.name for tool in gateway.tool_calls))),
        "tool_arguments": (
            tuple(tool.valid_arguments for tool in direct.tool_calls),
            tuple(tool.valid_arguments for tool in gateway.tool_calls),
        ),
        "finish_reason": (_finish_class(direct.finish_reason), _finish_class(gateway.finish_reason)),
        "usage_presence": (direct.usage_present, gateway.usage_present),
        "reasoning_presence": (direct.reasoning_present, gateway.reasoning_present),
        "json": (json.dumps(direct.json_value, sort_keys=True), json.dumps(gateway.json_value, sort_keys=True)),
        "error_code": (direct.error_code, gateway.error_code),
    }
    return tuple(name for name, pair in values.items() if pair[0] != pair[1])


def compare(direct: Observation, gateway: Observation, oracle: Oracle) -> Comparison:
    differences = _differences(direct, gateway)
    if "inconclusive" in {direct.outcome, gateway.outcome}:
        comparison = Comparison(verdict="inconclusive", differences=differences, reason="at least one path was inconclusive")
    else:
        direct_passes = satisfies(direct, oracle)
        gateway_passes = satisfies(gateway, oracle)
        if direct.outcome == "success" and direct_passes and not gateway_passes:
            comparison = Comparison(verdict="gateway_regression", differences=differences, reason="direct satisfied the oracle and gateway did not")
        elif direct.outcome != "success" and gateway.outcome == "success":
            comparison = Comparison(verdict="gateway_only_success", differences=differences, reason="only the gateway path succeeded")
        elif direct.outcome == gateway.outcome == "unsupported":
            comparison = Comparison(verdict="provider_limitation", differences=differences, reason="both paths reported unsupported behavior")
        elif direct.outcome != "success" and direct.outcome == gateway.outcome:
            comparison = Comparison(verdict="upstream_failure", differences=differences, reason="both paths failed in the same outcome class")
        elif direct_passes and gateway_passes and not differences:
            comparison = Comparison(verdict="parity")
        else:
            comparison = Comparison(verdict="different", differences=differences, reason="both paths completed with different normalized behavior")
    return comparison
