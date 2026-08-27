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


def test_pdf_input_is_required_and_exercised_on_every_completion_surface():
    features = load_features(ROOT / "definitions" / "features.yml")
    cases = load_cases(ROOT / "cases", features)
    pdf_feature = next(feature for feature in features.features if feature.name == "input_pdf")
    pdf_case = next(case for case in cases if case.id == "modalities.pdf")

    assert set(pdf_feature.endpoints) == {"chat/completions", "responses", "messages"}
    assert pdf_case.applies_to.endpoints == frozenset()


def test_case_ids_and_claims_are_stable_and_auditable():
    features = load_features(ROOT / "definitions" / "features.yml")
    cases = load_cases(ROOT / "cases", features)

    assert len({case.id for case in cases}) == len(cases)
    assert all(case.version == 2 and case.oracle.has_assertion and case.claims for case in cases)
