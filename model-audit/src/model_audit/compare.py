from __future__ import annotations

import json
import re

from model_audit.models import Assessment, FeatureVerdict, Observation, Oracle

UNSUPPORTED_PATTERNS = (
    "not supported",
    "unsupported",
    "does not support",
    "is not available",
    "cannot be used with",
    "may not be enabled when",
    "is incompatible with",
)
ACCESS_CODES = {"direct_authentication", "direct_model_access", "gateway_authentication", "not_run"}
HARNESS_CODES = {"client_exception", "connection_error", "harness_request_error", "http_protocol_error", "request_timeout", "sdk_protocol_error"}
ERROR_TOPICS = {
    "image": ("image", "vision"),
    "pdf": ("pdf", "document"),
    "reasoning": ("reasoning", "thinking", "effort"),
    "structured_output": ("json", "schema", "response_format"),
    "tools": ("tool", "function"),
    "temperature": ("temperature",),
    "top_p": ("top_p", "top p"),
    "stop": ("stop",),
    "seed": ("seed",),
    "tokens": ("max_tokens", "max tokens", "token limit"),
    "model": ("model",),
}


def _finish_class(reason: str | None) -> str | None:
    return {
        "end_turn": "stop",
        "stop": "stop",
        "completed": "stop",
        "tool_use": "tools",
        "tool_calls": "tools",
        "length": "length",
        "max_tokens": "length",
        "max_output_tokens": "length",
    }.get(reason, reason)


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
    if observation.outcome == "inconclusive" or _truncated_before_assertion(observation, oracle):
        return None
    return not oracle_failures(observation, oracle)


def explicit_unsupported(observation: Observation) -> bool:
    message = " ".join((observation.error_message or "").casefold().split())
    return observation.outcome == "rejected" and any(pattern in message for pattern in UNSUPPORTED_PATTERNS)


def feature_verdict(observation: Observation, oracle: Oracle) -> FeatureVerdict:
    direct_satisfies = satisfies(observation, oracle)
    if direct_satisfies is True:
        return "supported"
    if explicit_unsupported(observation) or (observation.outcome == "success" and direct_satisfies is False):
        return "unsupported"
    return "unknown"


def error_category(observation: Observation) -> str | None:
    if observation.outcome == "success":
        category = None
    elif observation.error_code in ACCESS_CODES:
        category = str(observation.error_code)
    elif observation.error_code in HARNESS_CODES:
        category = "client_protocol"
    elif explicit_unsupported(observation):
        category = "unsupported"
    else:
        code = (observation.error_code or "").casefold()
        message = (observation.error_message or "").casefold()
        if "rate" in code or "rate limit" in message:
            category = "rate_limit"
        elif observation.http_status is not None:
            topic = next((name for name, terms in ERROR_TOPICS.items() if any(term in message for term in terms)), None)
            suffix = f":{topic}" if topic is not None else ""
            category = f"http_{observation.http_status // 100}xx{suffix}"
        elif code:
            category = re.sub(r"[^a-z0-9]+", "_", code).strip("_")
        else:
            category = observation.outcome
    return category


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
        "error_category": (error_category(direct), error_category(gateway)),
        "adjustments": (direct.adjustments, gateway.adjustments),
    }
    return tuple(name for name, pair in values.items() if pair[0] != pair[1])


def assess(direct: Observation, gateway: Observation, oracle: Oracle) -> Assessment:
    direct_satisfies = satisfies(direct, oracle)
    gateway_satisfies = satisfies(gateway, oracle)
    feature = feature_verdict(direct, oracle)
    access_blocked = direct.error_code in ACCESS_CODES or gateway.error_code in ACCESS_CODES
    harness_error = direct.error_code in HARNESS_CODES or gateway.error_code in HARNESS_CODES
    if access_blocked:
        execution = "access_blocked"
    elif harness_error:
        execution = "harness_error"
    else:
        execution = "completed"
    differences = _differences(direct, gateway)
    oracle_differs = direct_satisfies is not None and gateway_satisfies is not None and direct_satisfies != gateway_satisfies
    if oracle_differs:
        differences = (*differences, "oracle")
    if access_blocked or harness_error or direct.outcome == "inconclusive" or gateway.outcome == "inconclusive":
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
        reason=reason,
        direct_satisfies_oracle=direct_satisfies,
        gateway_satisfies_oracle=gateway_satisfies,
    )
