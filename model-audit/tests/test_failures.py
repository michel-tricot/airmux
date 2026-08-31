from __future__ import annotations

from model_audit.failures import classify
from model_audit.models import Failure, Observation


def test_failure_classification_preserves_kind_subject_origin_and_retryability():
    observation = Observation(
        outcome="rejected",
        error_code="invalid_request_error",
        error_message="Thinking is not supported for this model",
        http_status=400,
        failure=Failure(
            kind="rejection",
            origin="direct",
            subject="reasoning",
            retryable=False,
            code="invalid_request_error",
            message="Thinking is not supported for this model",
            http_status=400,
        ),
    )

    failure = classify(observation)

    assert failure is not None
    assert failure.kind == "unsupported"
    assert failure.subject == "reasoning"
    assert failure.retryable is False


def test_unknown_and_unsupported_parameter_codes_share_one_category():
    direct = Observation(outcome="rejected", error_code="unsupported_parameter", error_message="Unsupported parameter: logprobs", http_status=400)
    gateway = Observation(outcome="rejected", error_code="unknown_parameter", error_message="Unknown parameter: logprobs", http_status=400)

    assert classify(direct) == classify(gateway)


def test_vendor_validation_codes_share_one_category_for_the_same_subject():
    direct = Observation(outcome="rejected", error_code="invalid_request_error", error_message="Invalid value for temperature", http_status=400)
    gateway = Observation(outcome="rejected", error_code="validation_error", error_message="Temperature failed validation", http_status=422)

    assert classify(direct) == classify(gateway)


def test_media_validation_terms_share_one_category():
    direct = Observation(
        outcome="rejected",
        error_code="400",
        error_message="Expected tagged-union[TextContent,ImageContent]",
        http_status=400,
    )
    gateway = Observation(outcome="rejected", error_code="400", error_message="pdf", http_status=400)

    direct_failure = classify(direct)
    gateway_failure = classify(gateway)

    assert direct_failure is not None
    assert gateway_failure is not None
    assert direct_failure.category == gateway_failure.category
