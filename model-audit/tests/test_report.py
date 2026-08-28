from __future__ import annotations

from model_audit.models import Assessment, Experiment, Observation, PairResult, Plan, ReportDocument, RunMetadata
from model_audit.report import checkpoint_interval, remaining_plan, write_report
from tests.helpers import case, target


def run_metadata(run_id: str) -> RunMetadata:
    return RunMetadata(
        run_id=run_id,
        created_at="2026-01-01T00:00:00+00:00",
        harness_commit="abc",
        gateway_url="http://gateway",
        taxonomy_fingerprint="catalog",
        client_versions={},
    )


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
            stability="flaky",
            feature="supported",
            parity="mismatch",
            differences=("outcome", "error_category", "oracle"),
            reason="direct and gateway behavior differ",
            direct_satisfies_oracle=True,
            gateway_satisfies_oracle=False,
        ),
    )

    paths = write_report(ReportDocument(run=run_metadata("run-test"), results=(result,)), tmp_path)

    document = paths.json_path.read_text(encoding="utf-8")
    report = paths.html_path.read_text(encoding="utf-8")
    assert '"feature": "supported"' in document
    assert '"parity": "mismatch"' in document
    assert '"stability": "flaky"' in document
    assert "Stability: 0 stable, 1 flaky" in report
    assert "gateway_rejection" in report
    assert "runs execute --model stub/model" in report
    assert "Direct:" in report
    assert "Gateway:" in report


def test_incomplete_report_retains_only_missing_experiments_for_resume():
    experiment_case = case()
    first = Experiment(
        target=target(model_id="stub/first", upstream_model="first"),
        case=experiment_case,
        direct_driver_id="http",
        gateway_driver_id="http",
        gateway_surface_id="oai",
        gateway_endpoint="chat/completions",
        transport="buffered",
    )
    second = first.model_copy(update={"target": target(model_id="stub/second", upstream_model="second")})
    completed = PairResult(
        case_id=experiment_case.id,
        case_version=experiment_case.version,
        case_fingerprint="fingerprint",
        claims=experiment_case.claims,
        provider_id="stub",
        surface_id="oai",
        endpoint="chat/completions",
        gateway_surface_id="oai",
        gateway_endpoint="chat/completions",
        model_id="stub/first",
        upstream_model="first",
        client="http",
        transport="buffered",
        direct=Observation(outcome="success"),
        gateway=Observation(outcome="success"),
        assessment=Assessment(execution="completed", feature="supported", parity="match"),
    )
    document = ReportDocument(
        run=run_metadata("run"),
        plan=Plan(experiments=(first, second)),
        complete=False,
        results=(completed,),
    )

    pending = remaining_plan(document)

    assert [experiment.target.model_id for experiment in pending.experiments] == ["stub/second"]


def test_checkpoint_records_plan_and_completion_state(tmp_path):
    experiment_case = case()
    experiment = Experiment(
        target=target(max_output_tokens=None),
        case=experiment_case,
        direct_driver_id="http",
        gateway_driver_id="http",
        gateway_surface_id="oai",
        gateway_endpoint="chat/completions",
        transport="buffered",
    )
    paths = write_report(
        ReportDocument(run=run_metadata("run-checkpoint"), plan=Plan(experiments=(experiment,)), complete=False, results=()),
        tmp_path,
    )

    document = ReportDocument.model_validate_json(paths.json_path.read_text(encoding="utf-8"))
    assert document.schema_version == 6
    assert document.complete is False
    assert document.plan is not None
    assert len(document.plan.experiments) == 1
    assert document.plan.experiments[0].target.max_output_tokens is None
    assert "runs resume" in paths.html_path.read_text(encoding="utf-8")


def test_checkpoint_interval_scales_with_large_plans():
    assert checkpoint_interval(3) == 1
    assert checkpoint_interval(100) == 1
    assert checkpoint_interval(22_501) == 226
