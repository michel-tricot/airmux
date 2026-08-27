from __future__ import annotations

from model_audit.models import Assessment, Observation, PairResult
from model_audit.report import write_report
from tests.helpers import case


def test_report_is_machine_readable_and_explains_gateway_gaps(tmp_path):
    experiment_case = case()
    result = PairResult(
        case_id=experiment_case.id,
        case_version=experiment_case.version,
        case_fingerprint="fingerprint",
        claims=experiment_case.claims,
        provider_id="stub",
        surface_id="oai",
        endpoint="chat/completions",
        gateway_surface_id="oai",
        gateway_endpoint="chat/completions",
        model_id="stub/model",
        upstream_model="model",
        client="http",
        transport="buffered",
        direct=Observation(outcome="success", text="ok"),
        gateway=Observation(outcome="rejected", http_status=400, error_code="invalid_request_error", error_message="bad request"),
        assessment=Assessment(
            execution="completed",
            feature="supported",
            parity="mismatch",
            differences=("outcome", "error_category", "oracle"),
            reason="direct and gateway behavior differ",
            direct_satisfies_oracle=True,
            gateway_satisfies_oracle=False,
        ),
    )

    paths = write_report([result], tmp_path, "run-test")

    document = paths.json_path.read_text(encoding="utf-8")
    report = paths.html_path.read_text(encoding="utf-8")
    assert '"feature": "supported"' in document
    assert '"parity": "mismatch"' in document
    assert "gateway_rejection" in report
    assert "runs execute --model stub/model" in report
    assert "Direct:" in report
    assert "Gateway:" in report
