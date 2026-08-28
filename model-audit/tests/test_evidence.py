from __future__ import annotations

import pytest

from model_audit.cases import fingerprint
from model_audit.evidence import records_from_report, reduce
from model_audit.models import (
    Assessment,
    EvidenceLedger,
    FeatureVerdict,
    Observation,
    PairResult,
    ReportDocument,
    RunMetadata,
)
from tests.helpers import case


def _report(
    run_id: str,
    created_at: str,
    feature: FeatureVerdict,
    client: str = "http",
    assessment: Assessment | None = None,
) -> ReportDocument:
    experiment_case = case()
    observation = Observation(outcome="success", text="ok")
    return ReportDocument(
        run=RunMetadata(
            run_id=run_id,
            created_at=created_at,
            harness_commit="abc",
            gateway_url="http://gateway",
            taxonomy_fingerprint="catalog",
            client_versions={},
        ),
        results=(
            PairResult(
                case_id=experiment_case.id,
                case_version=experiment_case.version,
                case_fingerprint=fingerprint(experiment_case),
                claims=experiment_case.claims,
                provider_id="stub",
                surface_id="oai",
                endpoint="chat/completions",
                gateway_surface_id="oai",
                gateway_endpoint="chat/completions",
                model_id="stub/model",
                upstream_model="model",
                client=client,
                transport="buffered",
                direct=observation,
                gateway=observation,
                assessment=assessment or Assessment(execution="completed", feature=feature, parity="match"),
            ),
        ),
    )


def test_unknown_evidence_does_not_overwrite_a_conclusive_observation():
    experiment_case = case()
    supported = records_from_report(_report("one", "2026-01-01T00:00:00+00:00", "supported"), (experiment_case,))
    unknown = records_from_report(_report("two", "2026-01-02T00:00:00+00:00", "unknown"), (experiment_case,))

    behavior = reduce(EvidenceLedger(records=(*supported, *unknown)), (experiment_case,))

    assert behavior.behaviors[0].verdict == "supported"
    assert behavior.behaviors[0].evidence_ids == (supported[0].evidence_id,)


def test_sdk_reports_cannot_become_provider_behavior_evidence():
    report = _report("sdk", "2026-01-01T00:00:00+00:00", "supported", client="openai")

    with pytest.raises(ValueError, match="SDK runs"):
        records_from_report(report, (case(),))


def test_interrupted_reports_cannot_become_provider_behavior_evidence():
    report = _report("partial", "2026-01-01T00:00:00+00:00", "supported").model_copy(update={"complete": False})

    with pytest.raises(ValueError, match="resume it before accepting evidence"):
        records_from_report(report, (case(),))


def test_incomplete_runs_do_not_become_provider_behavior_evidence():
    assessment = Assessment(execution="access_blocked", feature="unknown", parity="inconclusive")
    report = _report("blocked", "2026-01-01T00:00:00+00:00", "unknown", assessment=assessment)
    blocked = Observation(outcome="inconclusive", error_code="direct_authentication")
    report = report.model_copy(update={"results": (report.results[0].model_copy(update={"direct": blocked}),)})

    assert records_from_report(report, (case(),)) == ()


def test_transient_provider_failures_do_not_become_evidence():
    assessment = Assessment(execution="transient_failure", feature="unknown", parity="not_evaluated")
    report = _report("transient", "2026-01-01T00:00:00+00:00", "unknown", assessment=assessment)
    transient = Observation(outcome="transient", error_code="rate_limit", http_status=429)
    report = report.model_copy(update={"results": (report.results[0].model_copy(update={"direct": transient}),)})

    assert records_from_report(report, (case(),)) == ()


def test_flaky_provider_behavior_does_not_become_evidence():
    assessment = Assessment(execution="completed", feature="supported", parity="match", stability="flaky")
    report = _report("flaky", "2026-01-01T00:00:00+00:00", "supported", assessment=assessment)

    assert records_from_report(report, (case(),)) == ()


def test_gateway_failure_does_not_discard_a_valid_direct_observation():
    assessment = Assessment(execution="harness_error", feature="supported", parity="inconclusive")
    report = _report("gateway-failed", "2026-01-01T00:00:00+00:00", "supported", assessment=assessment)

    records = records_from_report(report, (case(),))

    assert len(records) == 1
    assert records[0].verdict == "supported"


def test_changed_cases_invalidate_previous_evidence():
    experiment_case = case()
    records = records_from_report(_report("one", "2026-01-01T00:00:00+00:00", "supported"), (experiment_case,))
    changed_case = experiment_case.model_copy(update={"title": "Changed case"})

    behavior = reduce(EvidenceLedger(records=records), (changed_case,))

    assert behavior.behaviors == ()


def test_reports_for_changed_cases_are_rejected_at_the_promotion_boundary():
    changed_case = case(title="Changed case")

    with pytest.raises(ValueError, match="stale or unknown cases"):
        records_from_report(_report("one", "2026-01-01T00:00:00+00:00", "supported"), (changed_case,))
