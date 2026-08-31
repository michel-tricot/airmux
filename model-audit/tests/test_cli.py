from __future__ import annotations

import json

from click import unstyle
from typer.testing import CliRunner

from model_audit.cli import _sync_steps, app


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
    assert experiments[0]["clients"] == "http"


def test_sdk_is_an_explicit_non_default_client_mode():
    result = CliRunner().invoke(
        app,
        ["runs", "plan", "--model", "openai/gpt-3.5-turbo", "--case", "text.basic", "--sdk", "--format", "json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["clients"] == "openai"


def test_case_option_accepts_namespaces_and_repeated_values():
    result = CliRunner().invoke(
        app,
        [
            "runs",
            "plan",
            "--model",
            "anthropic/claude-fable-5",
            "--case",
            "modalities",
            "--case",
            "text.basic",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert {experiment["case"] for experiment in json.loads(result.stdout)} == {"modalities.image", "modalities.pdf", "text.basic"}


def test_provider_option_selects_all_cataloged_models():
    result = CliRunner().invoke(app, ["runs", "plan", "--provider", "anthropic", "--case", "text.basic", "--format", "json"])

    assert result.exit_code == 0
    experiments = json.loads(result.stdout)
    assert len({experiment["model"] for experiment in experiments}) > 1
    assert {experiment["provider"] for experiment in experiments} == {"anthropic"}


def test_anthropic_models_can_use_the_openai_gateway_surface():
    result = CliRunner().invoke(
        app,
        ["runs", "plan", "--provider", "anthropic", "--gateway-surface", "oai", "--case", "text.basic", "--format", "json"],
    )

    assert result.exit_code == 0
    experiments = json.loads(result.stdout)
    assert experiments
    assert {experiment["provider_surface"] for experiment in experiments} == {"anthropic"}
    assert {experiment["gateway_surface"] for experiment in experiments} == {"oai"}


def test_all_gateway_surfaces_expand_the_matrix():
    result = CliRunner().invoke(
        app,
        ["runs", "plan", "--model", "anthropic/claude-fable-5", "--gateway-surface", "all", "--case", "text.basic", "--format", "json"],
    )

    assert result.exit_code == 0
    experiments = json.loads(result.stdout)
    assert {experiment["gateway_surface"] for experiment in experiments} == {"oai", "oai_responses", "anthropic"}


def test_unknown_gateway_surface_has_an_actionable_error():
    result = CliRunner().invoke(app, ["runs", "plan", "--gateway-surface", "unknown"])

    assert result.exit_code == 2
    assert "unknown gateway surface unknown" in result.output


def test_execute_exposes_a_single_global_concurrency_control():
    result = CliRunner().invoke(app, ["runs", "execute", "--help"])
    output = unstyle(result.output)

    assert result.exit_code == 0
    assert "--concurrency" in output
    assert "1<=x<=100" in output
    assert "--provider-concurrency" not in output


def test_interrupted_runs_have_a_resume_command():
    result = CliRunner().invoke(app, ["runs", "resume", "--help"])
    output = unstyle(result.output)

    assert result.exit_code == 0
    assert "report" in output
    assert "--concurrency" in output


def test_reports_expose_listing_and_retention_commands():
    result = CliRunner().invoke(app, ["reports", "--help"])

    assert result.exit_code == 0
    assert "list" in result.output
    assert "prune" in result.output


def test_provider_lifecycle_uses_onboard_and_sync_commands():
    providers = CliRunner().invoke(app, ["providers", "--help"])
    models = CliRunner().invoke(app, ["models", "--help"])

    assert providers.exit_code == 0
    assert "onboard" in providers.output
    assert "sources" in providers.output
    assert "sync" in providers.output
    assert " add " not in providers.output
    assert " refresh " not in providers.output
    assert models.exit_code == 0
    assert " refresh " not in models.output


def test_taxonomy_exposes_a_clean_rebuild_command():
    result = CliRunner().invoke(app, ["taxonomy", "--help"])

    assert result.exit_code == 0
    assert "rebuild" in result.output
    assert "diff" in result.output


def test_provider_sources_report_onboarding_readiness():
    result = CliRunner().invoke(app, ["providers", "sources", "--format", "json"])

    assert result.exit_code == 0
    sources = json.loads(result.stdout)
    anthropic = next(source for source in sources if source["id"] == "anthropic")
    assert anthropic["active"] == "yes"
    assert anthropic["definition"] == "ready"
    assert anthropic["schemas"] == 1


def test_unknown_provider_sync_component_is_rejected_before_acquisition():
    result = CliRunner().invoke(app, ["providers", "sync", "anthropic", "--only", "unknown"])

    assert result.exit_code == 2
    assert "unknown sync component unknown" in result.output


def test_model_and_pricing_sync_rebuild_enrichment_from_current_provider_data():
    pricing_steps = _sync_steps("stub", ("pricing",))
    model_steps = _sync_steps("stub", ("models",))

    assert [script for _, script, _ in pricing_steps] == ["fetch_models.py", "enrich.py"]
    assert [script for _, script, _ in model_steps] == ["fetch_models.py", "enrich.py", "discover_parameters.py"]
