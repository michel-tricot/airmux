from __future__ import annotations

import json

from provider_parity.models import Comparison, Observation, Oracle, Verdict


def _finish_class(reason: str | None) -> str | None:
    return {
        "end_turn": "stop",
        "stop": "stop",
        "tool_use": "tools",
        "tool_calls": "tools",
        "length": "length",
        "max_tokens": "length",
    }.get(reason, reason)


def oracle_failures(observation: Observation, oracle: Oracle) -> tuple[str, ...]:
    if observation.outcome != oracle.outcome:
        return (f"expected outcome {oracle.outcome}, got {observation.outcome}",)
    if observation.outcome != "success":
        return ()
    names = tuple(sorted(tool.name for tool in observation.tool_calls))
    expected_names = tuple(sorted(oracle.tool_names))
    checks = (
        (not oracle.text_nonempty or bool(observation.text.strip()), "expected non-empty assistant text"),
        (
            oracle.text_contains is None or oracle.text_contains.casefold() in observation.text.casefold(),
            f'expected assistant text containing "{oracle.text_contains}"',
        ),
        (oracle.assistant_text != "forbidden" or not observation.text.strip(), "expected no assistant text"),
        (oracle.assistant_text != "required" or bool(observation.text.strip()), "expected assistant text"),
        (not oracle.tool_names or names == expected_names, f"expected tool calls: {', '.join(expected_names)}"),
        (
            not oracle.tool_arguments_valid or all(tool.valid_arguments for tool in observation.tool_calls),
            "expected valid JSON object arguments for every tool call",
        ),
        (
            oracle.json_equals is None or observation.json_value == oracle.json_equals,
            f"expected JSON: {json.dumps(oracle.json_equals, sort_keys=True, ensure_ascii=False)}",
        ),
        (not oracle.reasoning_present or observation.reasoning_present, "expected reasoning output"),
    )
    return tuple(message for passed, message in checks if not passed)


def satisfies(observation: Observation, oracle: Oracle) -> bool:
    return not oracle_failures(observation, oracle)


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
    direct_passes = satisfies(direct, oracle)
    gateway_passes = satisfies(gateway, oracle)
    differences = _differences(direct, gateway) + (("oracle",) if direct_passes != gateway_passes else ())

    def result(verdict: Verdict, reason: str = "") -> Comparison:
        return Comparison(
            verdict=verdict,
            differences=differences,
            reason=reason,
            direct_satisfies_oracle=direct_passes,
            gateway_satisfies_oracle=gateway_passes,
        )

    if "inconclusive" in {direct.outcome, gateway.outcome}:
        comparison = result("inconclusive", "at least one path was inconclusive")
    elif direct.outcome == "success" and direct_passes and not gateway_passes:
        comparison = result("gateway_regression", "direct satisfied the oracle and gateway did not")
    elif direct.outcome != "success" and gateway.outcome == "success":
        comparison = result("gateway_only_success", "only the gateway path succeeded")
    elif direct.outcome == gateway.outcome == "unsupported":
        comparison = result("provider_limitation", "both paths reported unsupported behavior")
    elif direct.outcome != "success" and direct.outcome == gateway.outcome:
        comparison = result("upstream_failure", "both paths failed in the same outcome class")
    elif not differences:
        reason = "" if direct_passes else "both paths matched; neither satisfied the case oracle"
        comparison = result("parity", reason)
    else:
        comparison = result("different", "both paths completed with different normalized behavior")
    return comparison
