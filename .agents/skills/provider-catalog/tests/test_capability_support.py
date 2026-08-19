from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from capability_support import CAPABILITIES, PROBES, apply_discovery_evidence, discovery_evidence, resolve_capabilities, resolve_input_modalities
from evidence import CAPABILITY_PROBE_VERSION
from probe_capabilities import _probe_catalog, classify_response, image_challenge, probe_models, request_body
from probe_runtime import ProbeOutcome

PROVIDER = {
    "id": "example",
    "base_url": "https://example.com/v1",
    "ingress": ["oai"],
    "surfaces": {
        "oai": {
            "endpoint": "chat/completions",
            "auth": "bearer",
            "egress_kind": "openai_compatible",
            "headers": {},
        }
    },
}


def test_every_behavioral_probe_is_materialized():
    assert frozenset({"streaming", "image_input", "tools", "parallel_tools", "json_object", "json_schema", "reasoning"}) == PROBES
    assert frozenset({"streaming", "tools", "parallel_tools", "json_object", "json_schema", "reasoning"}) == CAPABILITIES


def test_live_probe_wins_over_catalog_capabilities():
    model = {
        "supports_tools": True,
        "capability_evidence": {
            "live_probe": {
                "support": {
                    "chat/completions": {
                        "streaming": "supported",
                        "tools": "unsupported",
                        "json_schema": "supported",
                    }
                }
            }
        },
    }

    assert resolve_capabilities(model, "chat/completions") == ["streaming", "json_schema"]


def test_stream_schema_is_discovery_evidence():
    provider = {
        "ingress": ["oai"],
        "schema": {
            "completion": {
                "oai": {
                    "request": "schemas/request.json",
                    "response": "schemas/response.json",
                    "stream": "schemas/stream.json",
                }
            }
        },
    }

    assert discovery_evidence(provider) == {
        "sources": ["schemas/stream.json"],
        "support": {"chat/completions": {"streaming": "supported"}},
    }


def test_refreshing_discovery_preserves_live_capability_evidence():
    live_probe = {"attempted": {"chat/completions": ["streaming"]}, "support": {"chat/completions": {"streaming": "unsupported"}}}
    models = [{"id": "new-model", "capability_evidence": {"live_probe": live_probe}}]
    discovery = {"sources": ["stream.json"], "support": {"chat/completions": {"streaming": "supported"}}}

    assert apply_discovery_evidence(models, discovery)[0]["capability_evidence"] == {
        "model_discovery": discovery,
        "live_probe": live_probe,
    }


def test_parallel_tools_implies_tools():
    model = {"capability_evidence": {"live_probe": {"support": {"chat/completions": {"parallel_tools": "supported"}}}}}

    assert resolve_capabilities(model, "chat/completions") == ["tools", "parallel_tools"]


def test_image_probe_overrides_catalog_modalities():
    model = {
        "input_modalities": ["text", "image"],
        "capability_evidence": {"live_probe": {"support": {"chat/completions": {"image_input": "unsupported"}}}},
    }

    assert resolve_input_modalities(model, "chat/completions") == ["text"]


def test_chat_image_probe_uses_an_inline_image():
    body = request_body("chat/completions", "new-model", "image_input")

    content = body["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_responses_image_probe_wraps_content_in_a_message_item():
    body = request_body("responses", "new-model", "image_input")

    assert body["input"][0]["type"] == "message"
    assert body["input"][0]["content"][1]["type"] == "input_image"


def test_parallel_tool_probe_requests_two_distinct_calls():
    body = request_body("chat/completions", "new-model", "parallel_tools")

    assert [tool["function"]["name"] for tool in body["tools"]] == ["report_alpha", "report_beta"]
    assert body["tool_choice"] == "required"
    assert "parallel_tool_calls" not in body


def test_json_schema_probe_supplies_a_strict_schema():
    body = request_body("responses", "new-model", "json_schema")

    output_format = body["text"]["format"]
    assert output_format["type"] == "json_schema"
    assert output_format["strict"] is True
    assert output_format["schema"]["required"] == ["answer"]


def test_reasoning_probe_asks_responses_for_a_summary():
    body = request_body("responses", "new-model", "reasoning")

    assert body["reasoning"] == {"effort": "low", "summary": "auto"}


def test_sse_response_proves_streaming():
    assert classify_response("streaming", 200, "text/event-stream", 'event: message\ndata: {"ok":true}\n\n') == "supported"


def test_two_function_calls_prove_parallel_tools():
    body = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"function": {"name": "report_alpha", "arguments": "{}"}},
                            {"function": {"name": "report_beta", "arguments": "{}"}},
                        ]
                    }
                }
            ]
        }
    )

    assert classify_response("parallel_tools", 200, "application/json", body) == "supported"


def test_one_function_call_leaves_parallel_tools_unknown():
    body = '{"choices":[{"message":{"tool_calls":[{"function":{"name":"report_alpha","arguments":"{}"}}]}}]}'

    assert classify_response("parallel_tools", 200, "application/json", body) is None


def test_a_token_limited_tool_probe_is_inconclusive():
    body = '{"choices":[{"message":{"content":""},"finish_reason":"length"}]}'

    assert classify_response("tools", 200, "application/json", body) is None


def test_image_probe_requires_the_exact_challenge_answer():
    _, _, expected = image_challenge("new-model")
    body = json.dumps({"choices": [{"message": {"content": expected}}]})

    assert classify_response("image_input", 200, "application/json", body, expected=expected) == "supported"
    assert classify_response("image_input", 200, "application/json", body, expected="wrong answer") is None


def test_valid_json_object_proves_json_object_mode():
    body = '{"choices":[{"message":{"content":"{\\"answer\\":42}"}}]}'

    assert classify_response("json_object", 200, "application/json", body) == "supported"


def test_invalid_json_schema_output_is_inconclusive_without_an_explicit_rejection():
    invalid = '{"choices":[{"message":{"content":"{\\"answer\\":\\"forty-two\\"}"}}]}'

    assert classify_response("json_schema", 200, "application/json", invalid) is None


def test_reasoning_item_proves_exposed_reasoning():
    body = '{"output":[{"type":"reasoning","summary":[{"type":"summary_text","text":"considered"}]}]}'

    assert classify_response("reasoning", 200, "application/json", body) == "supported"


def test_an_explicit_capability_rejection_is_conclusive():
    body = '{"error":"Image inputs are not supported by this model"}'

    assert classify_response("image_input", 400, "application/json", body) == "unsupported"


def test_non_sse_success_is_not_proof_streaming_is_unsupported():
    assert classify_response("streaming", 200, "application/json", '{"ok":true}') is None


def test_unexpected_runner_errors_fail_the_probe_run(monkeypatch):
    async def run():
        monkeypatch.setattr("probe_capabilities.probe", lambda *args: (_ for _ in ()).throw(RuntimeError("bug")))
        await _probe_catalog(PROVIDER, [{"id": "model"}], "key", None, False)

    with pytest.raises(RuntimeError, match="bug"):
        asyncio.run(run())


def test_probe_records_all_attempts_and_conclusive_results(monkeypatch):
    monkeypatch.setattr(
        "probe_capabilities.probe",
        lambda provider, model_id, endpoint, probe_name, key: ProbeOutcome(
            "unsupported" if probe_name == "image_input" else "supported",
            "explicit_rejection" if probe_name == "image_input" else "observed",
        ),
    )
    models: list[dict] = [{"id": "new-model"}]

    attempted, conclusive = probe_models(PROVIDER, models, "key")

    assert attempted == 7
    assert conclusive == 7
    evidence = models[0]["capability_evidence"]["live_probe"]
    assert evidence["version"] == CAPABILITY_PROBE_VERSION
    assert set(evidence["targets"]) == {"chat/completions"}
    assert set(evidence["attempted"]["chat/completions"]) == PROBES
    assert evidence["support"]["chat/completions"]["image_input"] == "unsupported"


def test_replacement_run_discards_evidence_from_an_old_classifier(monkeypatch):
    monkeypatch.setattr("probe_capabilities.probe", lambda provider, model_id, endpoint, probe_name, key: ProbeOutcome(None, "behavior_not_observed"))
    models = [
        {
            "id": "new-model",
            "capability_evidence": {
                "live_probe": {"attempted": {"chat/completions": ["tools"]}, "support": {"chat/completions": {"tools": "unsupported"}}}
            },
        }
    ]

    probe_models(PROVIDER, models, "key", replace=True)

    assert models[0]["capability_evidence"]["live_probe"]["support"] == {}


def test_changed_upstream_id_invalidates_old_evidence(monkeypatch):
    monkeypatch.setattr("probe_capabilities.probe", lambda provider, model_id, endpoint, probe_name, key: ProbeOutcome(None, "behavior_not_observed"))
    model = {"id": "model", "upstream_id": "new-target"}
    old = {
        "version": CAPABILITY_PROBE_VERSION,
        "targets": {"chat/completions": "old-target"},
        "attempted": {"chat/completions": ["tools"]},
        "support": {"chat/completions": {"tools": "supported"}},
    }
    model["capability_evidence"] = {"live_probe": old}

    probe_models(PROVIDER, [model], "key", probe_filter="image_input")

    live_probe = model["capability_evidence"]["live_probe"]
    assert live_probe["targets"] != old["targets"]
    assert live_probe["attempted"] == {"chat/completions": ["image_input"]}
    assert live_probe["support"] == {}


def test_every_cataloged_model_has_attempted_every_probe():
    taxonomy = SCRIPTS.parents[3] / "taxonomy"
    providers = {provider["id"]: provider for provider in yaml.safe_load((taxonomy / "providers.yml").read_text())["providers"]}
    endpoint_by_ingress = {"oai": "chat/completions", "oai_responses": "responses", "anthropic": "messages"}
    for path in sorted((taxonomy / "models").glob("*.json")):
        if path.stem not in providers:
            continue
        endpoints = {endpoint_by_ingress[ingress] for ingress in providers[path.stem]["ingress"] if ingress in endpoint_by_ingress}
        for model in json.loads(path.read_text())["models"]:
            attempted = ((model.get("capability_evidence") or {}).get("live_probe") or {}).get("attempted") or {}
            assert all(set(attempted.get(endpoint) or []) == PROBES for endpoint in endpoints), f"{path.stem}/{model['id']}"
