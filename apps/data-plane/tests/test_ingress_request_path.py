from __future__ import annotations

import json

import httpx
import openai
import pytest
from anthropic import Anthropic
from anthropic.types import Message, RawMessageStreamEvent
from conftest import TEXT_LOG, TEXT_NONSTREAM, GatewayTransport, mock_control_plane
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageFunctionToolCall
from pydantic import TypeAdapter
from starlette.testclient import TestClient
from yarl import URL

UPSTREAM = "https://api.openai.com/v1/chat/completions"


TEXT_BODY = {"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]}


def _sdk(client: TestClient, api_key: str) -> OpenAI:
    return OpenAI(base_url="http://testserver/inf/v1", api_key=api_key, http_client=client)


def _anthropic_sdk(client: httpx.Client, api_key: str) -> Anthropic:
    return Anthropic(base_url="http://testserver/inf", api_key=api_key, http_client=client)


STREAM_EVENT: TypeAdapter[RawMessageStreamEvent] = TypeAdapter(RawMessageStreamEvent)


def _post(client: TestClient, api_key: str, body: dict, **kwargs):
    return client.request("POST", "/inf/v1/messages", headers={"Authorization": f"Bearer {api_key}"}, json=body, **kwargs)


def test_openai_the_sdk_completes_a_text_round_trip(http_mock, api_key, dp_app):
    http_mock.post(UPSTREAM, status=200, payload=TEXT_NONSTREAM, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        completion = _sdk(client, api_key).chat.completions.create(model="gpt-test", messages=[{"role": "user", "content": "hi"}])
    assert completion.choices[0].message.content == "héllo \U0001f30d world"
    assert completion.choices[0].finish_reason == "stop"
    assert completion.usage is not None
    assert (completion.usage.prompt_tokens, completion.usage.completion_tokens, completion.usage.total_tokens) == (5, 7, 12)


def test_openai_the_sdk_completes_a_tool_round_trip(http_mock, api_key, dp_app):
    upstream_reply = {
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
    http_mock.post(UPSTREAM, status=200, payload=upstream_reply, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        completion = _sdk(client, api_key).chat.completions.create(
            model="gpt-test",
            messages=[
                {"role": "user", "content": "weather in Paris, then?"},
                {"role": "assistant", "tool_calls": [{"id": "c0", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "c0", "content": "cloudy"},
            ],
            tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}],
        )
    (call,) = completion.choices[0].message.tool_calls or []
    assert isinstance(call, ChatCompletionMessageFunctionToolCall)  # the SDK's union also covers custom tools
    assert (call.id, call.function.name) == ("call_1", "get_weather")
    assert json.loads(call.function.arguments) == {"city": "Paris"}

    sent = json.loads(http_mock.requests.get(("POST", URL(UPSTREAM)), [])[-1].kwargs["data"])
    assert [m["role"] for m in sent["messages"]] == ["user", "assistant", "tool"]  # the tool turn survives the double translation
    assert sent["tools"][0]["function"]["name"] == "get_weather"


def test_openai_the_sdk_parses_the_stream(http_mock, api_key, dp_app):
    http_mock.post(UPSTREAM, status=200, body=TEXT_LOG, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        stream = _sdk(client, api_key).chat.completions.create(model="gpt-test", messages=[{"role": "user", "content": "hi"}], stream=True)
        chunks = list(stream)
    text = "".join(c.choices[0].delta.content or "" for c in chunks if c.choices and c.choices[0].delta)
    assert text == "héllo \U0001f30d world"
    (usage_chunk,) = [c for c in chunks if c.usage is not None]
    assert usage_chunk.choices == []
    usage = usage_chunk.usage
    assert usage is not None
    assert (usage.prompt_tokens, usage.completion_tokens) == (5, 7)


def test_openai_what_the_gateway_dropped_is_visible_to_the_sdk_caller(http_mock, api_key, dp_app):
    http_mock.post(UPSTREAM, status=200, payload=TEXT_NONSTREAM, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        completion = _sdk(client, api_key).chat.completions.create(
            model="gpt-test", messages=[{"role": "user", "content": "hi"}], extra_body={"n": 2}
        )
    gateway = (completion.model_extra or {}).get("gateway")
    assert gateway is not None
    assert [(a["param"], a["action"]) for a in gateway["adjustments"]] == [
        ("n", "dropped"),
        ("max_output_tokens", "defaulted"),
    ]


def test_openai_supported_chat_reasoning_and_tool_options_reach_the_provider(http_mock, api_key, dp_app):
    http_mock.post(UPSTREAM, status=200, payload=TEXT_NONSTREAM, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                **TEXT_BODY,
                "reasoning_effort": "low",
                "parallel_tool_calls": True,
                "tools": [{"type": "function", "function": {"name": "answer", "parameters": {}, "strict": True}}],
            },
        )

    assert response.status_code == 200
    sent = json.loads(http_mock.requests.get(("POST", URL(UPSTREAM)), [])[-1].kwargs["data"])
    assert sent["reasoning_effort"] == "low"
    assert sent["parallel_tool_calls"] is True
    assert sent["tools"][0]["function"]["strict"] is True


def test_openai_a_forwardable_extra_reaches_the_provider_with_no_adjustment(http_mock, api_key, dp_app):
    http_mock.post(UPSTREAM, status=200, payload=TEXT_NONSTREAM, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        completion = _sdk(client, api_key).chat.completions.create(
            model="gpt-test", messages=[{"role": "user", "content": "hi"}], extra_body={"frequency_penalty": 0.5}
        )
    assert json.loads(http_mock.requests.get(("POST", URL(UPSTREAM)), [])[-1].kwargs["data"])["frequency_penalty"] == 0.5
    gateway = (completion.model_extra or {}).get("gateway")
    assert gateway == {
        "finish_reason": "stop",
        "adjustments": [
            {
                "param": "max_output_tokens",
                "action": "defaulted",
                "detail": "model caps output at 4096 tokens",
                "source": "model",
            }
        ],
    }


def test_openai_errors_come_back_in_the_callers_dialect(api_key, dp_app):
    """An SDK caller's rejection is an OpenAI-shaped error, so the SDK raises its typed exception
    with the gateway's code inside, instead of choking on a foreign envelope."""
    with TestClient(dp_app) as client, pytest.raises(openai.NotFoundError) as err:
        _sdk(client, api_key).chat.completions.create(model="ghost", messages=[{"role": "user", "content": "hi"}])
    assert "unknown_model" in str(err.value)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"user-agent": "OpenAI/Python 3.0.0"},
        {"x-airmux-dialect": "canonical"},
        {"x-airmux-dialect": "unknown"},
    ],
)
def test_chat_completions_path_always_returns_chat_completions(http_mock, api_key, dp_app, headers):
    http_mock.post(UPSTREAM, status=200, payload=TEXT_NONSTREAM, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        r = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", **headers},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    body = r.json()
    assert body["choices"][0]["message"]["content"] == "héllo \U0001f30d world"
    assert "content" not in body


def test_anthropic_a_cross_provider_round_trip_parses_with_the_sdk_models(http_mock, api_key, dp_app):
    """An Anthropic-speaking caller served by an OpenAI-family upstream: the route's reason to exist."""
    http_mock.post(UPSTREAM, status=200, payload=TEXT_NONSTREAM, repeat=True)
    mock_control_plane(http_mock)
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

    sent = json.loads(http_mock.requests.get(("POST", URL(UPSTREAM)), [])[-1].kwargs["data"])
    assert sent["messages"][0] == {"role": "system", "content": "You are terse."}  # hoisted system, respelled for OpenAI


def test_anthropic_the_documented_sdk_configuration_handles_buffered_and_streaming_responses(http_mock, api_key, dp_app):
    http_mock.post(UPSTREAM, status=200, payload=TEXT_NONSTREAM, repeat=False)
    http_mock.post(UPSTREAM, status=200, body=TEXT_LOG, repeat=False)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as gateway, httpx.Client(transport=GatewayTransport(gateway)) as transport:
        client = _anthropic_sdk(transport, api_key)
        message = client.messages.create(model="gpt-test", max_tokens=64, messages=[{"role": "user", "content": "hi"}])
        with client.messages.stream(model="gpt-test", max_tokens=64, messages=[{"role": "user", "content": "hi"}]) as stream:
            text = "".join(stream.text_stream)
    assert message.content[0].type == "text"
    assert message.content[0].text == "héllo \U0001f30d world"
    assert text == "héllo \U0001f30d world"


def test_anthropic_the_stream_parses_with_the_sdk_models(http_mock, api_key, dp_app):
    http_mock.post(UPSTREAM, status=200, body=TEXT_LOG, repeat=True)
    mock_control_plane(http_mock)
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


def test_anthropic_tools_translate_on_the_way_through(http_mock, api_key, dp_app):
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
    http_mock.post(UPSTREAM, status=200, payload=reply, repeat=True)
    mock_control_plane(http_mock)
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

    sent = json.loads(http_mock.requests.get(("POST", URL(UPSTREAM)), [])[-1].kwargs["data"])
    assert sent["tools"][0]["function"]["name"] == "get_weather"  # Anthropic tool shape respelled for OpenAI


def test_anthropic_errors_speak_this_dialect(api_key, dp_app):
    """The envelope the SDK maps to its typed exceptions: {type: error, error: {type, message}}."""
    with TestClient(dp_app) as client:
        response = _post(client, api_key, {"model": "ghost", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 404
    assert response.json() == {"type": "error", "error": {"type": "unknown_model", "message": ""}}


@pytest.mark.parametrize("stream", [False, True])
def test_anthropic_cross_provider_http_errors_speak_this_dialect(http_mock, api_key, dp_app, stream):
    http_mock.post(UPSTREAM, status=429, payload={"error": {"code": "rate_limit_exceeded", "message": "slow down"}}, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        response = _post(
            client,
            api_key,
            {"model": "gpt-test", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}], "stream": stream},
        )
    assert response.status_code == 429
    assert response.json() == {"type": "error", "error": {"type": "rate_limit_exceeded", "message": "slow down"}}


def test_anthropic_cross_provider_transport_errors_speak_this_dialect(http_mock, api_key, dp_app):
    http_mock.post(UPSTREAM, exception=TimeoutError("timed out"), repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        response = _post(client, api_key, {"model": "gpt-test", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 504
    assert response.json() == {"type": "error", "error": {"type": "upstream_timeout", "message": "upstream request timed out"}}
