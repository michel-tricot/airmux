from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "dependency_audit.py"


@pytest.fixture
def audit(monkeypatch):
    spec = importlib.util.spec_from_file_location("dependency_audit", MODULE_PATH)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "dependency_audit", module)
    spec.loader.exec_module(module)
    return module


def test_known_advisories_are_reported_without_failing(audit):
    report = '{"dependencies":[{"name":"example","version":"1.0","vulns":[{"id":"GHSA-test","fix_versions":["2.0"]}]}]}'
    assert "GHSA-test" in audit.summarize("python", report, 1, "all")


@pytest.mark.parametrize(("report", "status"), [("{}", 1), ("not-json", 1), ('{"error":"unavailable"}', 1), ("{}", 2)])
def test_failed_javascript_scans_are_not_treated_as_clean(audit, report, status):
    with pytest.raises(ValueError, match=r"Scanner|validation error"):
        audit.summarize("javascript", report, status, "all")


def test_empty_javascript_report_is_clean_only_on_success(audit):
    assert "0 advisory occurrences" in audit.summarize("javascript", "{}", 0, "production")


def test_skipped_python_dependencies_fail(audit):
    with pytest.raises(ValueError, match="validation errors"):
        audit.summarize("python", '{"dependencies":[{"name":"private","skip_reason":"not found"}]}', 0, "all")
