from __future__ import annotations

from typing import TYPE_CHECKING

from ci_report import app
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path


def test_ci_summary_shows_counts_variations_assertions_and_setup_errors(tmp_path: Path):
    reports = tmp_path / "results"
    reports.mkdir()
    (reports / "03-features.xml").write_text(
        '<testsuites><testsuite tests="3" failures="1" errors="1" skipped="0">'
        '<testcase classname="tests.gateway.test_features" name="tools[anthropic-stream]">'
        '<failure message="assert wrong == expected">assert wrong == expected\nsecret &lt;input&gt;</failure></testcase>'
        '<testcase classname="tests.gateway.test_features" name="setup">'
        '<error message="gateway exited">gateway exited before readiness</error></testcase>'
        '<testcase name="success" /></testsuite></testsuites>'
    )
    (reports / "04-policies.xml").write_text(
        '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="1"><testcase name="ok" />'
        '<testcase name="skipped"><skipped /></testcase></testsuite></testsuites>'
    )
    summary = tmp_path / "summary.md"
    result = CliRunner().invoke(app, [str(reports), "--summary", str(summary)])
    assert result.exit_code == 0, result.output
    contents = summary.read_text()
    assert "| 03-features | 3 | 1 | 1 | 0 |" in contents
    assert "| 04-policies | 2 | 0 | 0 | 1 |" in contents
    assert "tools[anthropic-stream]" in contents
    assert "assert wrong == expected" in contents
    assert "secret &lt;input&gt;" in contents
    assert "gateway exited before readiness" in contents
    assert result.output.count("::error") == 2


def test_ci_annotations_escape_workflow_commands_and_summary_markup(tmp_path: Path):
    (tmp_path / "failures.xml").write_text(
        '<testsuite tests="1" failures="1" errors="0" skipped="0"><testcase name="&lt;script&gt;">'
        '<failure message="bad%value&#10;::warning::injected">&lt;/pre&gt;&lt;script&gt;bad&lt;/script&gt;</failure>'
        "</testcase></testsuite>"
    )
    summary = tmp_path / "summary.md"
    result = CliRunner().invoke(app, [str(tmp_path), "--summary", str(summary)])
    assert result.exit_code == 0, result.output
    assert "bad%25value%0A::warning::injected" in result.output
    assert "\n::warning::injected" not in result.output
    assert "</pre><script>" not in summary.read_text()


def test_ci_summary_explains_missing_reports(tmp_path: Path):
    summary = tmp_path / "summary.md"
    result = CliRunner().invoke(app, [str(tmp_path / "missing"), "--summary", str(summary)])
    assert result.exit_code == 0, result.output
    assert "No test reports were produced" in summary.read_text()


def test_ci_summary_records_commit_runtime_and_candidate_digests(tmp_path: Path, monkeypatch):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "SHA256SUMS").write_text("abc  airmux.whl\n")
    summary = tmp_path / "summary.md"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")
    result = CliRunner().invoke(app, [str(tmp_path / "results"), "--summary", str(summary)])
    assert result.exit_code == 0, result.output
    contents = summary.read_text()
    assert "Commit: `deadbeef`" in contents
    assert "Python: `" in contents
    assert "abc  airmux.whl" in contents


def test_ci_summary_combines_reports_downloaded_from_parallel_jobs(tmp_path: Path):
    for level in ("01-basic", "02-protocols"):
        reports = tmp_path / f"gateway-integration-{level}" / "gateway-results"
        reports.mkdir(parents=True)
        (reports / f"{level}.xml").write_text('<testsuite tests="2" failures="0" errors="0" skipped="0" />')
    summary = tmp_path / "summary.md"
    result = CliRunner().invoke(app, [str(tmp_path), "--summary", str(summary)])
    assert result.exit_code == 0, result.output
    assert "| 01-basic | 2 | 0 | 0 | 0 |" in summary.read_text()
    assert "| 02-protocols | 2 | 0 | 0 | 0 |" in summary.read_text()
