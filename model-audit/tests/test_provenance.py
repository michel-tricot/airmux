from __future__ import annotations

from uuid import UUID

from model_audit.provenance import harness_fingerprint, new_run_id


def test_run_ids_are_unique_uuid7_values():
    first = UUID(new_run_id())
    second = UUID(new_run_id())

    assert first.version == 7
    assert second.version == 7
    assert first != second


def test_harness_fingerprint_changes_with_a_case_definition(tmp_path):
    project = tmp_path / "model-audit"
    (project / "src" / "model_audit").mkdir(parents=True)
    (project / "cases").mkdir()
    (project / "definitions").mkdir()
    (project / "pyproject.toml").write_text("project", encoding="utf-8")
    case = project / "cases" / "case.yml"
    case.write_text("first", encoding="utf-8")
    first = harness_fingerprint(tmp_path)
    case.write_text("second", encoding="utf-8")

    assert harness_fingerprint(tmp_path) != first
