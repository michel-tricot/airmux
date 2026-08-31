from __future__ import annotations

import os
import subprocess
import sys

import pytest

from model_audit.cases import fingerprint
from model_audit.evidence import accept, load_ledger, records_from_report, reduce
from model_audit.models import (
    Assessment,
    Claim,
    ClaimAssessment,
    EvidenceLedger,
    FeatureSummary,
    Observation,
    Oracle,
    PairResult,
    ReportDocument,
    RunMetadata,
)
from tests.helpers import case


def test_case_fingerprint_is_stable_across_hash_seeds():
    script = """
from model_audit.cli import _cases
from model_audit.cases import fingerprint

case = next(case for case in _cases() if case.id == "reasoning.exposed")
print(fingerprint(case))
"""

    def fingerprint_with_seed(seed: int) -> str:
        environment = {**os.environ, "PYTHONHASHSEED": str(seed)}
        result = subprocess.run(  # noqa: S603 fixed interpreter and static script are test-controlled
            [sys.executable, "-c", script], check=True, capture_output=True, text=True, env=environment
        )
        return result.stdout.strip()

    assert fingerprint_with_seed(1) == fingerprint_with_seed(4)


def _report(
    run_id: str,
    created_at: str,
    feature: FeatureSummary,
    client: str = "http",
    assessment: Assessment | None = None,
) -> ReportDocument:
    experiment_case = case()
    observation = Observation(outcome="success", text="ok")
    default_claims = tuple(
        ClaimAssessment(
            claim=claim,
            feature=feature if feature != "mixed" else "unknown",
            direct_satisfies=feature == "supported",
            gateway_satisfies=feature == "supported",
        )
        for claim in experiment_case.claims
    )
    resolved_assessment = assessment or Assessment(execution="completed", feature=feature, parity="match")
    if not resolved_assessment.claims:
        resolved_assessment = resolved_assessment.model_copy(update={"claims": default_claims})
    return ReportDocument(
        run=RunMetadata(
            run_id=run_id,
            created_at=created_at,
            harness_commit="abc",
            harness_fingerprint="harness",
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
                assessment=resolved_assessment,
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


def test_accept_can_replace_the_existing_ledger(tmp_path):
    experiment_case = case()
    ledger_path = tmp_path / "accepted.json"
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(_report("first", "2026-01-01T00:00:00+00:00", "supported").model_dump_json(), encoding="utf-8")
    second_path.write_text(_report("second", "2026-01-02T00:00:00+00:00", "supported").model_dump_json(), encoding="utf-8")
    accept(first_path, ledger_path, (experiment_case,))

    accept(second_path, ledger_path, (experiment_case,), replace=True)

    records = load_ledger(ledger_path).records
    assert len(records) == 1
    assert records[0].harness_fingerprint == "harness"
    assert records[0].observed_at == "2026-01-02T00:00:00+00:00"


def test_reports_for_changed_cases_are_rejected_at_the_promotion_boundary():
    changed_case = case(title="Changed case")

    with pytest.raises(ValueError, match="stale or unknown cases"):
        records_from_report(_report("one", "2026-01-01T00:00:00+00:00", "supported"), (changed_case,))


def test_evidence_uses_each_claims_own_feature_verdict():
    report = _report("claims", "2026-01-01T00:00:00+00:00", "mixed")
    result = report.results[0]
    supported = Claim(dimension="capability", name="tool_calling")
    unsupported = Claim(dimension="option", name="tool_choice", profile={"mode": "required"})
    assessment = result.assessment.model_copy(
        update={
            "claims": (
                ClaimAssessment(claim=supported, feature="supported", direct_satisfies=True, gateway_satisfies=True),
                ClaimAssessment(claim=unsupported, feature="unsupported", direct_satisfies=False, gateway_satisfies=False),
            )
        }
    )
    result = result.model_copy(update={"claims": (supported, unsupported), "assessment": assessment})
    changed_case = case(claims=(supported, unsupported))
    result = result.model_copy(update={"case_fingerprint": fingerprint(changed_case)})
    report = report.model_copy(update={"results": (result,)})

    records = records_from_report(report, (changed_case,))

    assert [(record.claim.name, record.verdict) for record in records] == [
        ("tool_calling", "supported"),
        ("tool_choice", "unsupported"),
    ]


def test_evidence_stores_claim_identity_without_case_assertions():
    experiment_case = case(claims=(Claim(dimension="capability", name="text_generation", assertion=Oracle(text_nonempty=True)),))
    report = _report("assertion", "2026-01-01T00:00:00+00:00", "supported")
    result = report.results[0].model_copy(
        update={
            "claims": experiment_case.claims,
            "case_fingerprint": fingerprint(experiment_case),
            "assessment": report.results[0].assessment.model_copy(
                update={
                    "claims": (
                        ClaimAssessment(
                            claim=experiment_case.claims[0],
                            feature="supported",
                            direct_satisfies=True,
                            gateway_satisfies=True,
                        ),
                    )
                }
            ),
        }
    )
    report = report.model_copy(update={"results": (result,)})

    records = records_from_report(report, (experiment_case,))

    assert records[0].claim.assertion is None
