from __future__ import annotations

from model_audit.compare import assess
from model_audit.models import Observation, Oracle


def test_matching_explicit_rejections_are_parity_and_unsupported():
    direct = Observation(outcome="rejected", http_status=400, error_code="invalid_request_error", error_message="This option is not supported")
    gateway = direct.model_copy(update={"error_message": "The option is unsupported for this model"})

    result = assess(direct, gateway, Oracle(text_nonempty=True))

    assert result.feature == "unsupported"
    assert result.parity == "match"


def test_matching_generic_rejections_are_parity_but_unknown_support():
    direct = Observation(outcome="rejected", http_status=400, error_code="invalid_request_error", error_message="Could not process image")

    result = assess(direct, direct, Oracle(text_nonempty=True))

    assert result.feature == "unknown"
    assert result.parity == "match"


def test_different_generic_rejection_topics_are_not_false_parity():
    direct = Observation(outcome="rejected", http_status=400, error_code="invalid_request_error", error_message="Could not process image")
    gateway = direct.model_copy(update={"error_message": "Tool choice is invalid"})

    result = assess(direct, gateway, Oracle(text_nonempty=True))

    assert result.feature == "unknown"
    assert result.parity == "mismatch"
    assert "error_category" in result.differences


def test_direct_success_and_gateway_rejection_is_a_gateway_gap():
    direct = Observation(outcome="success", text="ok", usage_present=True)
    gateway = Observation(outcome="rejected", http_status=400, error_code="invalid_request_error", error_message="bad request")

    result = assess(direct, gateway, Oracle(text_contains="ok"))

    assert result.feature == "supported"
    assert result.parity == "mismatch"
    assert "oracle" in result.differences


def test_success_without_the_claimed_behavior_is_unsupported():
    result = assess(
        Observation(outcome="success", text="not a tool"), Observation(outcome="success", text="not a tool"), Oracle(tool_names=("lookup",))
    )

    assert result.feature == "unsupported"
    assert result.parity == "match"


def test_equivalent_cross_dialect_completion_reasons_match():
    direct = Observation(outcome="success", text="ok", finish_reason="end_turn")
    gateway = Observation(outcome="success", text="ok", finish_reason="completed")

    result = assess(direct, gateway, Oracle(text_contains="ok"))

    assert result.parity == "match"


def test_responses_output_limit_before_oracle_is_unknown():
    direct = Observation(outcome="success", finish_reason="max_output_tokens", usage_present=True)

    result = assess(direct, direct, Oracle(text_nonempty=True))

    assert result.feature == "unknown"
    assert result.parity == "match"
