from __future__ import annotations

from pathlib import Path

from model_audit.cases import coverage, load_cases, load_features

ROOT = Path(__file__).resolve().parents[1]


def test_case_matrix_covers_every_required_feature():
    features = load_features(ROOT / "definitions" / "features.yml")
    cases = load_cases(ROOT / "cases", features)

    result = coverage(cases, features)

    assert result.missing == ()
    assert result.missing_endpoint_coverage == ()
    assert result.unmapped_request_fields == ()
    assert result.case_count >= 25
    assert "option:parallel_tool_calls" in result.covered
    assert "modality:input_pdf" in result.covered
    assert "interaction:streaming+tools" in result.covered


def test_case_ids_and_claims_are_stable_and_auditable():
    features = load_features(ROOT / "definitions" / "features.yml")
    cases = load_cases(ROOT / "cases", features)

    assert len({case.id for case in cases}) == len(cases)
    assert all(case.version == 2 and case.oracle.has_assertion and case.claims for case in cases)
