from __future__ import annotations

from provider_parity.compare import compare
from provider_parity.models import Observation, Oracle, ToolObservation

ORACLE = Oracle(tool_names=("report_alpha", "report_beta"), tool_arguments_valid=True, assistant_text="forbidden")
PASSING = Observation(
    outcome="success",
    tool_calls=(ToolObservation(name="report_alpha", arguments="{}"), ToolObservation(name="report_beta", arguments="{}")),
    finish_reason="tool_calls",
    usage_present=True,
)


def test_equivalent_semantic_observations_are_parity():
    result = compare(PASSING, PASSING.model_copy(update={"duration_ms": 99}), ORACLE)

    assert result.verdict == "parity"
    assert result.differences == ()


def test_a_gateway_failure_after_direct_success_is_a_regression():
    gateway = Observation(outcome="error", error_code="invalid_upstream_response")

    result = compare(PASSING, gateway, ORACLE)

    assert result.verdict == "gateway_regression"
    assert "outcome" in result.differences


def test_matching_unsupported_results_preserve_the_provider_limitation():
    unsupported = Observation(outcome="unsupported", error_code="unsupported_parameter")

    result = compare(unsupported, unsupported, Oracle(outcome="unsupported"))

    assert result.verdict == "provider_limitation"


def test_gateway_only_success_is_reported_as_a_difference():
    direct = Observation(outcome="unsupported", error_code="unsupported_parameter")
    gateway = Observation(outcome="success", text="ok", adjustments=("temperature:dropped",))

    result = compare(direct, gateway, Oracle(text_nonempty=True))

    assert result.verdict == "gateway_only_success"
    assert "outcome" in result.differences
