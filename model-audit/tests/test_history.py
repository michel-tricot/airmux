from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx

from model_audit.cases import load_cases, load_features
from model_audit.drivers.base import Connection
from model_audit.drivers.http import HTTPDriver

ROOT = Path(__file__).resolve().parents[1]


def _case():
    cases = load_cases(ROOT / "cases", load_features(ROOT / "definitions" / "features.yml"))
    return next(case for case in cases if case.id == "reasoning.history")


@respx.mock
def test_responses_history_replays_provider_reasoning_items():
    route = respx.post("https://provider.example/v1/responses")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "id": "resp_1",
                "status": "completed",
                "output": [
                    {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "signature"},
                    {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "It is even"}]},
                ],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        ),
        httpx.Response(
            200,
            json={
                "id": "resp_2",
                "status": "completed",
                "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "42"}]}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        ),
    ]
    connection = Connection(base_url="https://provider.example/v1", api_key="key", auth="bearer", headers={}, route="direct")

    observation = HTTPDriver().execute(connection, "responses", "model", _case(), "buffered")

    second = json.loads(route.calls[1].request.content)
    assert observation.text == "42"
    assert second["input"][1]["type"] == "reasoning"
    assert second["input"][1]["encrypted_content"] == "signature"


@respx.mock
def test_anthropic_history_replays_provider_thinking_signature():
    route = respx.post("https://provider.example/v1/messages")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "content": [
                    {"type": "thinking", "thinking": "42 is divisible by two", "signature": "signature"},
                    {"type": "text", "text": "It is even"},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        ),
        httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "42"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        ),
    ]
    connection = Connection(
        base_url="https://provider.example/v1",
        api_key="key",
        auth="header_key:x-api-key",
        headers={},
        route="direct",
    )

    observation = HTTPDriver().execute(connection, "messages", "model", _case(), "buffered")

    second = json.loads(route.calls[1].request.content)
    assert observation.text == "42"
    assert second["messages"][1]["content"][0]["signature"] == "signature"
