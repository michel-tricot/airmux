from __future__ import annotations

import json

from typer.testing import CliRunner

from model_audit.cli import app


def test_cases_have_machine_readable_coverage():
    result = CliRunner().invoke(app, ["cases", "coverage", "--format", "json"])

    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert {row["status"] for row in rows} == {"covered", "excluded"}
    assert any(row["claim"] == "option:reasoning_effort" for row in rows)


def test_one_model_and_case_produces_a_bounded_plan():
    result = CliRunner().invoke(
        app,
        ["runs", "plan", "--model", "openai/gpt-3.5-turbo", "--case", "text.basic", "--format", "json"],
    )

    assert result.exit_code == 0
    experiments = json.loads(result.stdout)
    assert experiments[0]["model"] == "openai/gpt-3.5-turbo"
    assert experiments[0]["client"] == "http"


def test_sdk_is_an_explicit_non_default_client_mode():
    result = CliRunner().invoke(
        app,
        ["runs", "plan", "--model", "openai/gpt-3.5-turbo", "--case", "text.basic", "--sdk", "--format", "json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["client"] == "openai"
