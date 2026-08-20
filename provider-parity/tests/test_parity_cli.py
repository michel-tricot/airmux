from __future__ import annotations

from typer.testing import CliRunner

from provider_parity.cli import app


def test_cases_are_listed_in_machine_readable_form():
    result = CliRunner().invoke(app, ["cases", "list", "--format", "json"])

    assert result.exit_code == 0
    assert '"id": "tools.parallel"' in result.stdout


def test_a_single_model_and_case_produces_a_bounded_plan():
    result = CliRunner().invoke(
        app,
        ["runs", "plan", "--model", "openai/gpt-3.5-turbo", "--case", "text.basic", "--transport", "buffered", "--format", "json"],
    )

    assert result.exit_code == 0
    assert '"model": "openai/gpt-3.5-turbo"' in result.stdout
    assert "paired experiments" in result.stderr
