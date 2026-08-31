from __future__ import annotations

import json

import httpx
import respx

from model_audit.drivers.base import Connection
from model_audit.drivers.http import HTTPDriver
from tests.helpers import case


def _connection() -> Connection:
    return Connection(base_url="https://provider.example/v1", api_key="key", auth="bearer", headers={}, route="direct")


@respx.mock
def test_chat_stream_without_done_is_a_provider_protocol_error():
    event = {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}
    respx.post("https://provider.example/v1/chat/completions").mock(return_value=httpx.Response(200, content=f"data: {json.dumps(event)}\n\n"))

    observation = HTTPDriver().execute(_connection(), "chat/completions", "model", case(), "streamed")

    assert observation.outcome == "error"
    assert observation.error_code == "invalid_upstream_response"


@respx.mock
def test_responses_stream_error_event_preserves_the_gateway_error():
    event = {"type": "error", "error": {"code": "invalid_upstream_response", "message": "provider stream ended before its terminal event"}}
    respx.post("https://provider.example/v1/responses").mock(return_value=httpx.Response(200, content=f"data: {json.dumps(event)}\n\n"))

    observation = HTTPDriver().execute(_connection(), "responses", "model", case(), "streamed")

    assert observation.outcome == "error"
    assert observation.error_code == "invalid_upstream_response"
    assert observation.error_message == "provider stream ended before its terminal event"
