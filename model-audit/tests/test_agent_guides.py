from __future__ import annotations

import json

from typer.testing import CliRunner

from model_audit.cli import app


def test_agent_guides_are_discoverable_as_machine_readable_resources():
    result = CliRunner().invoke(app, ["agent", "guides", "--format", "json"])

    assert result.exit_code == 0
    guides = json.loads(result.stdout)
    assert {guide["id"] for guide in guides} == {
        "behavior-audit",
        "gateway-investigation",
        "model-update",
        "provider-onboarding",
        "provider-sync",
        "taxonomy-generation",
    }
    versions = {guide["id"]: guide["version"] for guide in guides}
    assert versions["provider-onboarding"] == 3
    assert versions["provider-sync"] == 2
    assert versions["model-update"] == 2
    assert versions["taxonomy-generation"] == 3
    unchanged = {"behavior-audit", "gateway-investigation"}
    assert {guide_id for guide_id, version in versions.items() if version == 1} == unchanged


def test_provider_onboarding_guide_is_owned_by_the_cli():
    result = CliRunner().invoke(app, ["agent", "guide", "provider-onboarding", "--format", "text"])

    assert result.exit_code == 0
    assert "providers onboard" in result.stdout
    assert "vendor-owned" in result.stdout
    assert "ProviderDefinition" in result.stdout
    assert "input modalities" in result.stdout
    assert "capabilities" in result.stdout
    assert "at least one input and one output" in result.stdout
    assert "A 200 is not a success" in result.stdout


def test_taxonomy_generation_guide_defines_modality_projection():
    result = CliRunner().invoke(app, ["agent", "guide", "taxonomy-generation", "--format", "text"])

    assert result.exit_code == 0
    assert "directional content types" in result.stdout
    assert "accepted direct evidence overrides" in result.stdout
    assert "must have at least one input" in result.stdout


def test_unknown_agent_guide_has_an_actionable_error():
    result = CliRunner().invoke(app, ["agent", "guide", "missing"])

    assert result.exit_code == 2
    assert "unknown agent guide missing" in result.output
