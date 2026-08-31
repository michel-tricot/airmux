from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from model_audit.failures import ACCESS_CODES, HARNESS_CODES, classify, explicit_unsupported
from model_audit.models import Assessment, Case, ClaimAssessment, Difference, FeatureSummary, FeatureVerdict, Observation, Oracle

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pydantic import JsonValue


def _finish_class(reason: str | None) -> str | None:
    return {
        "end_turn": "stop",
        "stop": "stop",
        "stop_sequence": "stop",
        "completed": "stop",
        "tool_use": "tools",
        "tool_calls": "tools",
        "length": "length",
        "max_tokens": "length",
        "max_output_tokens": "length",
    }.get(reason, reason)


def _semantic_finish(observation: Observation) -> str | None:
    finish = _finish_class(observation.finish_reason)
    return "tools" if observation.tool_calls and finish in {"stop", "tools"} else finish


def oracle_failures(observation: Observation, oracle: Oracle) -> tuple[str, ...]:
    if observation.outcome != "success":
        return (f"expected a successful response, got {observation.outcome}",)
    names = tuple(sorted(tool.name for tool in observation.tool_calls))
    expected_names = tuple(sorted(oracle.tool_names))
    checks = (
        (not oracle.text_nonempty or bool(observation.text.strip()), "expected non-empty assistant text"),
        (
            oracle.text_contains is None or oracle.text_contains.casefold() in observation.text.casefold(),
            f'expected assistant text containing "{oracle.text_contains}"',
        ),
        (
            oracle.text_excludes is None or oracle.text_excludes.casefold() not in observation.text.casefold(),
            f'expected assistant text excluding "{oracle.text_excludes}"',
        ),
        (oracle.assistant_text != "forbidden" or not observation.text.strip(), "expected no assistant text"),
        (oracle.assistant_text != "required" or bool(observation.text.strip()), "expected assistant text"),
        (not oracle.tool_names or names == expected_names, f"expected tool calls: {', '.join(expected_names)}"),
        (
            not oracle.tool_arguments_valid or all(tool.valid_arguments for tool in observation.tool_calls),
            "expected valid JSON object arguments for every tool call",
        ),
        (
            not oracle.tool_arguments
            or all(
                any(tool.name == name and tool.parsed_arguments == arguments for tool in observation.tool_calls)
                for name, arguments in oracle.tool_arguments.items()
            ),
            f"expected tool arguments: {json.dumps(oracle.tool_arguments, sort_keys=True, ensure_ascii=False)}",
        ),
        (
            oracle.json_equals is None or observation.json_value == oracle.json_equals,
            f"expected JSON: {json.dumps(oracle.json_equals, sort_keys=True, ensure_ascii=False)}",
        ),
        (not oracle.reasoning_present or observation.reasoning_present, "expected reasoning output"),
        (not oracle.usage_present or observation.usage_present, "expected usage"),
    )
    return tuple(message for passed, message in checks if not passed)


def _truncated_before_assertion(observation: Observation, oracle: Oracle) -> bool:
    return _finish_class(observation.finish_reason) == "length" and bool(oracle_failures(observation, oracle))


def satisfies(observation: Observation, oracle: Oracle) -> bool | None:
    if observation.outcome in {"inconclusive", "transient"} or _truncated_before_assertion(observation, oracle):
        return None
    return not oracle_failures(observation, oracle)


def feature_verdict(observation: Observation, oracle: Oracle) -> FeatureVerdict:
    direct_satisfies = satisfies(observation, oracle)
    if direct_satisfies is True:
        return "supported"
    if explicit_unsupported(observation) or (observation.outcome == "success" and direct_satisfies is False):
        return "unsupported"
    return "unknown"


def error_category(observation: Observation) -> str | None:
    failure = classify(observation)
    return failure.category if failure is not None else None


def _json_value(value: object) -> JsonValue:
    return cast("JsonValue", json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False)))


def _tool_arguments(observation: Observation, exact: bool) -> JsonValue:
    if exact:
        return _json_value([{"name": tool.name, "arguments": tool.parsed_arguments} for tool in observation.tool_calls])
    return _json_value([{"name": tool.name, "valid": tool.valid_arguments} for tool in observation.tool_calls])


def _oracles(case: Case) -> tuple[Oracle, ...]:
    return tuple(claim.assertion or case.oracle for claim in case.claims)


def _dimensions(case: Case) -> frozenset[str]:
    oracles = _oracles(case)
    inferred = set()
    if any(oracle.usage_present for oracle in oracles):
        inferred.add("usage")
    if any(oracle.reasoning_present for oracle in oracles):
        inferred.add("reasoning")
    if any(oracle.json_equals is not None for oracle in oracles):
        inferred.add("json")
    return frozenset({*case.comparison.dimensions, *inferred})


def _differences(direct: Observation, gateway: Observation, case: Case) -> tuple[Difference, ...]:
    dimensions = _dimensions(case)
    exact_arguments = any(oracle.tool_arguments for oracle in _oracles(case))
    values: dict[str, tuple[object, object]] = {
        "outcome": (direct.outcome, gateway.outcome),
        "text": (direct.text, gateway.text),
        "tool_calls": (tuple(tool.name for tool in direct.tool_calls), tuple(tool.name for tool in gateway.tool_calls)),
        "tool_arguments": (_tool_arguments(direct, exact_arguments), _tool_arguments(gateway, exact_arguments)),
        "finish_reason": (_semantic_finish(direct), _semantic_finish(gateway)),
        "usage": (
            direct.usage.model_dump(mode="json") if direct.usage is not None else None,
            gateway.usage.model_dump(mode="json") if gateway.usage is not None else None,
        ),
        "reasoning": (direct.reasoning_present, gateway.reasoning_present),
        "json": (direct.json_value, gateway.json_value),
        "error": (error_category(direct), error_category(gateway)),
        "adjustments": (direct.adjustments, gateway.adjustments),
    }
    return tuple(
        Difference(code=code, direct=_json_value(pair[0]), gateway=_json_value(pair[1]))
        for code, pair in values.items()
        if code in dimensions and pair[0] != pair[1]
    )


def _claim_assessments(direct: Observation, gateway: Observation, case: Case) -> tuple[ClaimAssessment, ...]:
    return tuple(
        ClaimAssessment(
            claim=claim,
            feature=feature_verdict(direct, oracle),
            direct_satisfies=satisfies(direct, oracle),
            gateway_satisfies=satisfies(gateway, oracle),
        )
        for claim in case.claims
        for oracle in (claim.assertion or case.oracle,)
    )


def _feature_summary(claims: Iterable[ClaimAssessment]) -> FeatureSummary:
    verdicts = {claim.feature for claim in claims}
    if len(verdicts) == 1:
        return verdicts.pop()
    return "unknown" if "unknown" in verdicts else "mixed"


def behavior_signature(observation: Observation, case: Case) -> tuple[object, ...]:
    return (
        observation.outcome,
        tuple(tool.name for tool in observation.tool_calls),
        tuple((tool.name, json.dumps(tool.parsed_arguments, sort_keys=True)) for tool in observation.tool_calls),
        _semantic_finish(observation),
        error_category(observation),
        tuple(satisfies(observation, oracle) for oracle in _oracles(case)),
    )


def _mirrored_access_failure(direct: Observation, gateway: Observation) -> bool:
    direct_message = " ".join((direct.error_message or "").casefold().split())
    gateway_message = " ".join((gateway.error_message or "").casefold().split())
    return (
        (direct.error_code in ACCESS_CODES or gateway.error_code in ACCESS_CODES)
        and direct.http_status in {401, 403, 404, 429}
        and direct.http_status == gateway.http_status
        and bool(direct_message)
        and direct_message == gateway_message
    )


def assess(direct: Observation, gateway: Observation, case: Case) -> Assessment:
    direct_satisfies = satisfies(direct, case.oracle)
    gateway_satisfies = satisfies(gateway, case.oracle)
    claims = _claim_assessments(direct, gateway, case)
    feature = _feature_summary(claims)
    access_blocked = direct.error_code in ACCESS_CODES or gateway.error_code in ACCESS_CODES
    harness_error = direct.error_code in HARNESS_CODES or gateway.error_code in HARNESS_CODES
    transient_failure = direct.outcome == "transient" or gateway.outcome == "transient"
    if access_blocked:
        execution = "access_blocked"
    elif harness_error:
        execution = "harness_error"
    elif transient_failure:
        execution = "transient_failure"
    else:
        execution = "completed"
    mirrored_access_failure = _mirrored_access_failure(direct, gateway)
    differences = () if mirrored_access_failure else _differences(direct, gateway, case)
    oracle_differs = direct_satisfies is not None and gateway_satisfies is not None and direct_satisfies != gateway_satisfies
    if oracle_differs:
        differences = (*differences, Difference(code="oracle", direct=direct_satisfies, gateway=gateway_satisfies))
    if mirrored_access_failure:
        parity = "match"
        reason = "gateway mirrors provider access failure"
    elif transient_failure and not access_blocked and not harness_error:
        parity = "not_evaluated"
        reason = "a transient failure prevented comparison"
    elif access_blocked or harness_error or direct.outcome == "inconclusive" or gateway.outcome == "inconclusive":
        parity = "inconclusive"
        reason = "access or transport prevented a meaningful comparison"
    elif differences:
        parity = "mismatch"
        reason = "direct and gateway behavior differ"
    else:
        parity = "match"
        reason = "direct and gateway behavior match"
    return Assessment(
        execution=execution,
        feature=feature,
        parity=parity,
        differences=differences,
        claims=claims,
        reason=reason,
        direct_satisfies_oracle=direct_satisfies,
        gateway_satisfies_oracle=gateway_satisfies,
    )
