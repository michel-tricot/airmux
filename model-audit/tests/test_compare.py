from __future__ import annotations

from model_audit.compare import assess
from model_audit.models import Claim, Observation, Oracle, UsageObservation
from tests.helpers import case


def _case(oracle: Oracle):
    return case(oracle=oracle)


def test_matching_explicit_rejections_are_parity_and_unsupported():
    direct = Observation(outcome="rejected", http_status=400, error_code="invalid_request_error", error_message="This option is not supported")
    gateway = direct.model_copy(update={"error_message": "The option is unsupported for this model"})

    result = assess(direct, gateway, _case(Oracle(text_nonempty=True)))

    assert result.feature == "unsupported"
    assert result.parity == "match"


def test_model_specific_not_enabled_rejection_is_unsupported():
    messages = ("reasoning_effort is not enabled for this model", "Logprobs are not enabled for this model")

    for message in messages:
        direct = Observation(outcome="rejected", http_status=400, error_code="3051", error_message=message)
        result = assess(direct, direct, _case(Oracle(text_nonempty=True)))

        assert result.feature == "unsupported"
        assert result.parity == "match"


def test_matching_generic_rejections_are_parity_but_unknown_support():
    direct = Observation(outcome="rejected", http_status=400, error_code="invalid_request_error", error_message="Could not process image")

    result = assess(direct, direct, _case(Oracle(text_nonempty=True)))

    assert result.feature == "unknown"
    assert result.parity == "match"


def test_matching_provider_access_denials_are_parity_but_unknown_support():
    message = "Model access must be enabled for this organization"
    direct = Observation(outcome="inconclusive", http_status=403, error_code="direct_authentication", error_message=message)
    gateway = Observation(outcome="error", http_status=403, error_code="1913", error_message=message)

    result = assess(direct, gateway, _case(Oracle(text_nonempty=True)))

    assert result.execution == "access_blocked"
    assert result.feature == "unknown"
    assert result.parity == "match"
    assert result.differences == ()


def test_matching_model_not_found_responses_are_parity_but_unknown_support():
    message = "Model not found, inaccessible, and/or not deployed"
    direct = Observation(outcome="inconclusive", http_status=404, error_code="direct_model_access", error_message=message)
    gateway = Observation(outcome="rejected", http_status=404, error_code="NOT_FOUND", error_message=message)

    result = assess(direct, gateway, _case(Oracle(text_nonempty=True)))

    assert result.execution == "access_blocked"
    assert result.feature == "unknown"
    assert result.parity == "match"
    assert result.differences == ()


def test_different_generic_rejection_topics_are_not_false_parity():
    direct = Observation(outcome="rejected", http_status=400, error_code="invalid_request_error", error_message="Could not process image")
    gateway = direct.model_copy(update={"error_message": "Tool choice is invalid"})

    result = assess(direct, gateway, _case(Oracle(text_nonempty=True)))

    assert result.feature == "unknown"
    assert result.parity == "mismatch"
    assert "error" in result.difference_codes


def test_direct_success_and_gateway_rejection_is_a_gateway_gap():
    direct = Observation(outcome="success", text="ok", usage_present=True)
    gateway = Observation(outcome="rejected", http_status=400, error_code="invalid_request_error", error_message="bad request")

    result = assess(direct, gateway, _case(Oracle(text_contains="ok")))

    assert result.feature == "supported"
    assert result.parity == "mismatch"
    assert "oracle" in result.difference_codes


def test_success_without_the_claimed_behavior_is_unsupported():
    result = assess(
        Observation(outcome="success", text="not a tool"),
        Observation(outcome="success", text="not a tool"),
        _case(Oracle(tool_names=("lookup",))),
    )

    assert result.feature == "unsupported"
    assert result.parity == "match"


def test_equivalent_cross_dialect_completion_reasons_match():
    direct = Observation(outcome="success", text="ok", finish_reason="end_turn")
    gateway = Observation(outcome="success", text="ok", finish_reason="completed")

    result = assess(direct, gateway, _case(Oracle(text_contains="ok")))

    assert result.parity == "match"


def test_stop_sequence_and_stop_are_equivalent_completion_reasons():
    direct = Observation(outcome="success", text="ok", finish_reason="stop_sequence")
    gateway = Observation(outcome="success", text="ok", finish_reason="stop")

    result = assess(direct, gateway, _case(Oracle(text_contains="ok")))

    assert result.parity == "match"


def test_responses_output_limit_before_oracle_is_unknown():
    direct = Observation(outcome="success", finish_reason="max_output_tokens", usage_present=True)

    result = assess(direct, direct, _case(Oracle(text_nonempty=True)))

    assert result.feature == "unknown"
    assert result.parity == "match"


def test_incidental_reasoning_does_not_create_a_mismatch():
    direct = Observation(outcome="success", text="red", reasoning_present=True)
    gateway = Observation(outcome="success", text="red", reasoning_present=False)

    result = assess(direct, gateway, _case(Oracle(text_contains="red")))

    assert result.parity == "match"


def test_incidental_parseable_json_does_not_create_a_mismatch():
    direct = Observation(outcome="success", text="20 + 22 = 42", reasoning_present=True)
    gateway = Observation(outcome="success", text="42", json_value=42, reasoning_present=True)

    result = assess(direct, gateway, _case(Oracle(text_contains="42", reasoning_present=True)))

    assert result.parity == "match"
    assert "json" not in result.difference_codes


def test_claimed_reasoning_presence_still_participates_in_parity():
    direct = Observation(outcome="success", text="ok", reasoning_present=True)
    gateway = Observation(outcome="success", text="ok", reasoning_present=False)

    result = assess(direct, gateway, _case(Oracle(text_contains="ok", reasoning_present=True)))

    assert result.parity == "mismatch"
    assert "reasoning" in result.difference_codes


def test_claimed_usage_compares_reported_token_counts():
    direct = Observation(
        outcome="success",
        text="ok",
        usage_present=True,
        usage=UsageObservation(input_tokens=10, output_tokens=2, total_tokens=12),
    )
    gateway = Observation(
        outcome="success",
        text="ok",
        usage_present=True,
        usage=UsageObservation(input_tokens=11, output_tokens=2, total_tokens=13),
    )

    result = assess(direct, gateway, _case(Oracle(text_contains="ok", usage_present=True)))

    assert result.parity == "mismatch"
    assert "usage" in result.difference_codes


def test_transient_failure_does_not_produce_a_parity_verdict():
    direct = Observation(outcome="success", text="ok")
    gateway = Observation(outcome="transient", error_code="rate_limit", http_status=429)

    result = assess(direct, gateway, _case(Oracle(text_contains="ok")))

    assert result.execution == "transient_failure"
    assert result.parity == "not_evaluated"
    assert result.feature == "supported"


def test_malformed_gateway_response_is_a_protocol_mismatch():
    direct = Observation(outcome="success", text="ok")
    gateway = Observation(outcome="error", error_code="http_protocol_error", error_message="missing terminal event")

    result = assess(direct, gateway, _case(Oracle(text_contains="ok")))

    assert result.execution == "completed"
    assert result.parity == "mismatch"
    assert result.feature == "supported"


def test_matching_provider_billing_failures_are_parity_but_access_blocked():
    message = "The provider account credit balance is exhausted"
    direct = Observation(outcome="inconclusive", http_status=429, error_code="provider_billing_access", error_message=message)
    gateway = direct.model_copy()

    result = assess(direct, gateway, _case(Oracle(text_nonempty=True)))

    assert result.execution == "access_blocked"
    assert result.feature == "unknown"
    assert result.parity == "match"


def test_each_claim_has_an_independent_feature_verdict():
    audit_case = case(
        claims=(
            Claim(dimension="capability", name="tool_calling", assertion=Oracle(tool_names=("lookup",))),
            Claim(dimension="option", name="tool_choice", profile={"mode": "required"}, assertion=Oracle(assistant_text="forbidden")),
        ),
        oracle=Oracle(tool_names=("lookup",)),
    )
    direct = Observation(
        outcome="success",
        text="I also answered",
        tool_calls=({"name": "lookup", "arguments": '{"value":"ok"}'},),
    )

    result = assess(direct, direct, audit_case)

    assert [(claim.claim.name, claim.feature) for claim in result.claims] == [
        ("tool_calling", "supported"),
        ("tool_choice", "unsupported"),
    ]
    assert result.feature == "mixed"


def test_tool_argument_values_participate_in_parity_when_claimed():
    oracle = Oracle(tool_names=("lookup",), tool_arguments={"lookup": {"value": "ok"}})
    direct = Observation(outcome="success", tool_calls=({"name": "lookup", "arguments": '{"value":"ok"}'},))
    gateway = Observation(outcome="success", tool_calls=({"name": "lookup", "arguments": '{"value":"wrong"}'},))

    result = assess(direct, gateway, _case(oracle))

    assert result.parity == "mismatch"
    assert "tool_arguments" in result.difference_codes
    difference = next(difference for difference in result.differences if difference.code == "tool_arguments")
    assert difference.direct == [{"name": "lookup", "arguments": {"value": "ok"}}]
    assert difference.gateway == [{"name": "lookup", "arguments": {"value": "wrong"}}]
