from __future__ import annotations

from pathlib import Path

import yaml

from model_audit.models import BehaviorRecord, Claim
from model_audit.taxonomy import _capabilities, _parameter_support, _provider_entry

ROOT = Path(__file__).resolve().parents[2]


def behavior(dimension: str, name: str, verdict: str, *, surface: str = "oai", profile: dict | None = None) -> BehaviorRecord:
    return BehaviorRecord.model_validate(
        {
            "provider_id": "stub",
            "model_id": "stub/model",
            "surface_id": surface,
            "endpoint": "chat/completions",
            "claim": Claim.model_validate({"dimension": dimension, "name": name, "profile": profile or {}}),
            "verdict": verdict,
            "evidence_ids": ["evidence"],
            "observed_at": "2026-01-01T00:00:00+00:00",
        }
    )


def test_profile_rejection_does_not_erase_a_broader_capability():
    model = {"supports_thinking": True}
    rejected_low_effort = behavior("capability", "reasoning", "unsupported", profile={"effort": "low"})

    assert "reasoning" in _capabilities(model, [rejected_low_effort])


def test_profile_rejection_does_not_mark_an_entire_option_unsupported():
    model = {"parameter_evidence": {"model_discovery": {"support": {"chat/completions": {"reasoning_effort": "supported"}}}}}
    rejected_low_effort = behavior("option", "reasoning_effort", "unsupported", profile={"value": "low"})

    support = _parameter_support(model, "chat/completions", [rejected_low_effort])

    assert support["reasoning_effort"] == "supported"


def test_provider_gateway_profile_is_preserved_in_generated_taxonomy():
    provider = {
        "id": "openai",
        "base_url": "https://api.openai.com/v1",
        "param_aliases": {"max_tokens": "max_completion_tokens"},
        "params_closed": True,
        "accepted_params": ["verbosity"],
    }

    assert _provider_entry(provider, "icon") == {
        "provider_id": "openai",
        "kind": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "icon": "icon",
        "param_aliases": {"max_tokens": "max_completion_tokens"},
        "params_closed": True,
        "accepted_params": ["verbosity"],
    }


def test_openai_catalog_declares_its_output_limit_alias():
    document = yaml.safe_load((ROOT / "taxonomy/providers.yml").read_text(encoding="utf-8"))
    provider = next(item for item in document["providers"] if item["id"] == "openai")

    assert provider["param_aliases"]["max_tokens"] == "max_completion_tokens"


def test_gpt_5_6_models_route_through_responses():
    document = yaml.safe_load((ROOT / "taxonomy/taxonomy.yml").read_text(encoding="utf-8"))
    models = {item["model_id"]: item for item in document["models"]}

    for model_id in ("openai/gpt-5.6-luna", "openai/gpt-5.6-sol", "openai/gpt-5.6-terra"):
        assert models[model_id]["egress_kind"] == "openai_responses"


def test_gpt_5_3_codex_routes_through_responses():
    document = yaml.safe_load((ROOT / "taxonomy/taxonomy.yml").read_text(encoding="utf-8"))
    models = {item["model_id"]: item for item in document["models"]}

    assert models["openai/gpt-5.3-codex"]["egress_kind"] == "openai_responses"
