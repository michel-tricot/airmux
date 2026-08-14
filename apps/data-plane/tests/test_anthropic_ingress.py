"""The Anthropic-shaped surface at /v1/messages.

The official SDK's own models are the arbiter: they must parse every byte the route returns,
buffered and streamed, including across providers, since a Messages caller routed to an
OpenAI-family upstream is the point of the route. The live claude-gateway script is the
full-transport proof."""

from __future__ import annotations

import json

import httpx
import respx
from anthropic.types import Message, RawMessageStreamEvent
from conftest import TEXT_LOG, TEXT_NONSTREAM
from pydantic import TypeAdapter
from starlette.testclient import TestClient

from data_plane.canonical import CanonicalResponse, ReasoningPart, TextPart, Usage
from data_plane.ingress.anthropic import AnthropicIngress

UPSTREAM = "https://api.openai.com/v1/chat/completions"

STREAM_EVENT: TypeAdapter[RawMessageStreamEvent] = TypeAdapter(RawMessageStreamEvent)


def _post(client: TestClient, api_key: str, body: dict, **kwargs):
    return client.request("POST", "/v1/messages", headers={"Authorization": f"Bearer {api_key}"}, json=body, **kwargs)


def test_parse_hoists_system_and_keeps_the_rest_as_extras():
    body = {
        "model": "gpt-test",
        "max_tokens": 64,
        "system": "You are terse.",
        "messages": [{"role": "user", "content": "hi"}],
        "stop_sequences": ["END"],
        "thinking": {"type": "enabled", "budget_tokens": 512},
        "metadata": {"user_id": "u1"},
    }
    req, adjustments = AnthropicIngress().parse(body)
    assert [m.role for m in req.messages] == ["system", "user"]
    assert req.max_tokens == 64
    assert req.stop == ["END"]
    assert req.extra == {"thinking": {"type": "enabled", "budget_tokens": 512}, "metadata": {"user_id": "u1"}}
    assert adjustments == []


def test_parse_strips_client_directive_blocks():
    body = {
        "model": "gpt-test",
        "max_tokens": 8,
        "system": [{"type": "text", "text": "x-anthropic-billing: abc"}, {"type": "text", "text": "Real prompt"}],
        "messages": [{"role": "user", "content": "hi"}],
    }
    req, _ = AnthropicIngress().parse(body)
    (system, _user) = req.messages
    assert [part.text for part in system.content if part.type == "text"] == ["Real prompt"]


def test_the_sdk_reads_a_thinking_signature_back():
    """The signature must survive the render: a Messages caller replays it on the next turn."""
    final = CanonicalResponse(
        id="msg_1",
        model="m",
        content=[ReasoningPart(text="think", signature="sig_1"), TextPart(text="ok")],
        finish_reason="stop",
        usage=Usage(input_tokens=3, output_tokens=2),
    )
    message = Message.model_validate_json(bytes(AnthropicIngress().render_response(final).body))
    thinking = message.content[0]
    assert thinking.type == "thinking"
    assert (thinking.thinking, thinking.signature) == ("think", "sig_1")


@respx.mock
def test_a_cross_provider_round_trip_parses_with_the_sdk_models(api_key, dp_app):
    """An Anthropic-speaking caller served by an OpenAI-family upstream: the route's reason to exist."""
    route = respx.post(UPSTREAM).mock(return_value=httpx.Response(200, json=TEXT_NONSTREAM))
    with TestClient(dp_app) as client:
        response = _post(
            client, api_key, {"model": "gpt-test", "max_tokens": 64, "system": "You are terse.", "messages": [{"role": "user", "content": "hi"}]}
        )
    assert response.status_code == 200, response.text
    message = Message.model_validate_json(response.content)
    assert message.content[0].type == "text"
    assert message.content[0].text == "héllo \U0001f30d world"
    assert message.stop_reason == "end_turn"
    assert (message.usage.input_tokens, message.usage.output_tokens) == (5, 7)

    sent = json.loads(route.calls.last.request.content)
    assert sent["messages"][0] == {"role": "system", "content": "You are terse."}  # hoisted system, respelled for OpenAI


@respx.mock
def test_the_stream_parses_with_the_sdk_models(api_key, dp_app):
    respx.post(UPSTREAM).mock(return_value=httpx.Response(200, content=TEXT_LOG))
    with TestClient(dp_app) as client:
        response = _post(client, api_key, {"model": "gpt-test", "max_tokens": 64, "messages": [{"role": "user", "content": "hi"}], "stream": True})
    payloads = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
    events = [STREAM_EVENT.validate_json(payload) for payload in payloads if json.loads(payload)["type"] != "ping"]  # the SDK skips pings too
    kinds = [event.type for event in events]
    assert kinds[0] == "message_start"
    assert kinds[-2:] == ["message_delta", "message_stop"]
    text = "".join(e.delta.text for e in events if e.type == "content_block_delta" and e.delta.type == "text_delta")
    assert text == "héllo \U0001f30d world"
    (message_delta,) = [e for e in events if e.type == "message_delta"]
    assert message_delta.delta.stop_reason == "end_turn"
    assert message_delta.usage is not None
    assert message_delta.usage.output_tokens == 7


@respx.mock
def test_tools_translate_on_the_way_through(api_key, dp_app):
    reply = {
        "id": "chatcmpl-9",
        "model": "gpt-real",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'}}],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
    }
    route = respx.post(UPSTREAM).mock(return_value=httpx.Response(200, json=reply))
    with TestClient(dp_app) as client:
        response = _post(
            client,
            api_key,
            {
                "model": "gpt-test",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "weather in Paris?"}],
                "tools": [{"name": "get_weather", "description": "Get weather", "input_schema": {"type": "object"}}],
            },
        )
    message = Message.model_validate_json(response.content)
    (call,) = message.content
    assert call.type == "tool_use"
    assert (call.id, call.name, call.input) == ("call_1", "get_weather", {"city": "Paris"})
    assert message.stop_reason == "tool_use"

    sent = json.loads(route.calls.last.request.content)
    assert sent["tools"][0]["function"]["name"] == "get_weather"  # Anthropic tool shape respelled for OpenAI


def test_errors_speak_this_dialect(api_key, dp_app):
    """The envelope the SDK maps to its typed exceptions: {type: error, error: {type, message}}."""
    with TestClient(dp_app) as client:
        response = _post(client, api_key, {"model": "ghost", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 404
    assert response.json() == {"type": "error", "error": {"type": "unknown_model", "message": ""}}
