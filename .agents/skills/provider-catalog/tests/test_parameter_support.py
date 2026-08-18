from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from parameter_support import apply_discovery_evidence, classify_parameter_response, discovery_evidence, resolve_parameter_support
from probe_parameters import PROBES, probe_models, request_body, routable_models


def test_live_probe_wins_over_model_discovery():
    evidence = {
        "model_discovery": {"support": {"responses": {"temperature": "supported", "top_p": "supported"}}},
        "live_probe": {"support": {"responses": {"temperature": "unsupported"}}},
    }
    assert resolve_parameter_support(evidence, "responses") == {"temperature": "unsupported", "top_p": "supported"}


def test_model_discovery_fills_an_unprobed_parameter():
    evidence = {"model_discovery": {"support": {"responses": {"temperature": "supported"}}}}
    assert resolve_parameter_support(evidence, "responses") == {"temperature": "supported"}


def test_discovery_evidence_comes_from_the_provider_request_schema(tmp_path: Path):
    schema = tmp_path / "oai.example.request.json"
    schema.write_text(
        """{
  "type": "object",
  "properties": {
    "temperature": {"type": "number"},
    "stop": {"type": "array"},
    "reasoning_effort": {"type": "string"}
  }
}
"""
    )
    provider = {
        "schema": {"completion": {"oai": {"request": schema.name}}},
        "ingress": ["oai"],
    }

    assert discovery_evidence(provider, tmp_path) == {
        "sources": [schema.name],
        "support": {
            "chat/completions": {
                "reasoning_effort": "supported",
                "stop": "supported",
                "temperature": "supported",
            }
        },
    }


def test_refreshing_discovery_preserves_live_probe_results():
    live_probe = {
        "attempted": {"responses": ["temperature"]},
        "support": {"responses": {"temperature": "unsupported"}},
    }
    models = [{"id": "new-model", "parameter_evidence": {"live_probe": live_probe}}]
    discovery = {"sources": ["request.json"], "support": {"responses": {"temperature": "supported"}}}

    assert apply_discovery_evidence(models, discovery)[0]["parameter_evidence"] == {
        "model_discovery": discovery,
        "live_probe": live_probe,
    }


def test_model_discovery_probe_records_attempts_and_conclusive_results(monkeypatch):
    monkeypatch.setattr(
        "probe_parameters.probe",
        lambda provider, model_id, endpoint, parameter, value, key: "unsupported" if parameter == "temperature" else None,
    )
    models = [{"id": "new-model", "parameter_evidence": {"model_discovery": {"sources": [], "support": {}}}}]

    attempted, conclusive = probe_models({"ingress": ["oai"]}, models, "key")

    assert attempted == 7
    assert conclusive == 1
    assert models[0]["parameter_evidence"]["live_probe"] == {
        "attempted": {
            "chat/completions": [
                "logprobs",
                "parallel_tool_calls",
                "reasoning_effort",
                "seed",
                "stop",
                "temperature",
                "top_p",
            ]
        },
        "support": {"chat/completions": {"temperature": "unsupported"}},
    }


def test_chat_probe_isolates_the_parameter_under_test():
    assert request_body("chat/completions", "new-model", "temperature", 0.7) == {
        "model": "new-model",
        "messages": [{"role": "user", "content": "say ok"}],
        "temperature": 0.7,
    }


def test_temperature_probe_uses_a_non_default_value():
    assert PROBES["chat/completions"]["temperature"] == 0.7
    assert PROBES["responses"]["temperature"] == 0.7


def test_manual_probe_selects_only_models_in_the_applied_taxonomy():
    catalog = {"models": [{"id": "advertised"}, {"id": "routable"}, {"id": "also-routable"}]}
    applied_model_ids = {"example/routable", "example/also-routable"}

    assert routable_models(catalog, "example", applied_model_ids, limit=1) == [{"id": "routable"}]


def test_every_cataloged_model_contains_discovery_evidence():
    taxonomy = SCRIPTS.parents[3] / "taxonomy"
    providers = yaml.safe_load((taxonomy / "providers.yml").read_text())["providers"]
    provider_ids = {provider["id"] for provider in providers}
    for path in sorted((taxonomy / "models").glob("*.json")):
        if path.stem not in provider_ids:
            continue
        models = json.loads(path.read_text())["models"]
        assert models
        assert all("model_discovery" in model.get("parameter_evidence", {}) for model in models), path.stem


def test_a_conclusive_unsupported_parameter_error_is_durable_evidence():
    body = '{"error":{"message":"Unsupported parameter: \'temperature\' is not supported with this model."}}'
    assert classify_parameter_response(400, body, "temperature") == "unsupported"


def test_a_dotted_parameter_name_is_recognized():
    body = '{"error":{"message":"Unsupported parameter: \'reasoning.effort\' is not supported with this model."}}'
    assert classify_parameter_response(400, body, "reasoning_effort") == "unsupported"


def test_a_generic_bad_request_is_not_parameter_evidence():
    assert classify_parameter_response(400, '{"error":{"message":"Bad request"}}', "temperature") is None
