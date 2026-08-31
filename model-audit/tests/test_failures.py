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
