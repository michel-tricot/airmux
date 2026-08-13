"""Unmodified OpenAI clients on the native route.

The official SDK is the arbiter: it must complete text, tool and streaming round trips against
the gateway with nothing changed but base_url and api_key. Its own response models parsing our
bytes is what makes this an invariant rather than an opinion. And the mirror invariant: a
canonical caller's answers never change shape, whatever the interpretation is doing."""

from __future__ import annotations

import json

import httpx
import openai
import pytest
import respx
from conftest import TEXT_LOG, TEXT_NONSTREAM
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageFunctionToolCall
from starlette.datastructures import Headers
from starlette.testclient import TestClient

from data_plane.ingress import resolve
from data_plane.ingress.openai import OpenAIIngress

UPSTREAM = "https://api.openai.com/v1/chat/completions"

TEXT_BODY = {"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]}
TOOL_ROLE_BODY = {
    "model": "gpt-test",
    "messages": [
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "w", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "18C"},
    ],
}
NESTED_TOOLS_BODY = {**TEXT_BODY, "tools": [{"type": "function", "function": {"name": "w", "parameters": {}}}]}
IMAGE_URL_BODY = {
    "model": "gpt-test",
    "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://x/cat.png"}}]}],
}


@pytest.mark.parametrize(
    ("body", "headers", "expected"),
    [
        (TEXT_BODY, {}, False),
        (TOOL_ROLE_BODY, {}, True),
        (NESTED_TOOLS_BODY, {}, True),
        ({**TEXT_BODY, "tool_choice": {"type": "function", "function": {"name": "w"}}}, {}, True),
        (IMAGE_URL_BODY, {}, True),
        ({**TEXT_BODY, "max_completion_tokens": 5}, {}, True),
        (TEXT_BODY, {"x-stainless-lang": "python"}, True),
        (TEXT_BODY, {"user-agent": "OpenAI/Python 3.0.0"}, True),
        (TEXT_BODY, {"x-airllm-dialect": "openai"}, True),
        (TOOL_ROLE_BODY, {"x-airllm-dialect": "canonical"}, False),
        (TEXT_BODY, {"x-stainless-lang": "python", "x-airllm-dialect": "canonical"}, False),
    ],
)
def test_detection(body, headers, expected):
    assert (resolve(Headers(headers), body).dialect == "openai") is expected


def test_parse_translates_the_openai_shapes_and_keeps_the_rest():
    body = {
        **TOOL_ROLE_BODY,
        "tools": [{"type": "function", "function": {"name": "w", "description": "weather", "parameters": {"type": "object"}}}],
        "tool_choice": {"type": "function", "function": {"name": "w"}},
        "max_completion_tokens": 64,
        "frequency_penalty": 0.5,
        "stream_options": {"include_usage": True},
    }
    req = OpenAIIngress().parse(body)
    roles = [(m.role, [p.type for p in m.content]) for m in req.messages]
    assert roles == [("user", ["text"]), ("assistant", ["tool_call"]), ("user", ["tool_result"])]
    assert req.tools is not None
    assert (req.tools[0].name, req.tools[0].description) == ("w", "weather")
    assert getattr(req.tool_choice, "name", None) == "w"
    assert req.max_tokens == 64
    assert req.extra == {"frequency_penalty": 0.5}  # stream_options consumed silently, the rest kept for the reconcile step


def _sdk(client: TestClient, token: str) -> OpenAI:
    return OpenAI(base_url="http://testserver/v1", api_key=token, http_client=client)


@respx.mock
def test_the_sdk_completes_a_text_round_trip(token, dp_app):
    respx.post(UPSTREAM).mock(return_value=httpx.Response(200, json=TEXT_NONSTREAM))
    with TestClient(dp_app) as client:
        completion = _sdk(client, token).chat.completions.create(model="gpt-test", messages=[{"role": "user", "content": "hi"}])
    assert completion.choices[0].message.content == "héllo \U0001f30d world"
    assert completion.choices[0].finish_reason == "stop"
    assert completion.usage is not None
    assert (completion.usage.prompt_tokens, completion.usage.completion_tokens, completion.usage.total_tokens) == (5, 7, 12)


@respx.mock
def test_the_sdk_completes_a_tool_round_trip(token, dp_app):
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
    route = respx.post(UPSTREAM).mock(return_value=httpx.Response(200, json=upstream_reply))
    with TestClient(dp_app) as client:
        completion = _sdk(client, token).chat.completions.create(
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

    sent = json.loads(route.calls.last.request.content)
    assert [m["role"] for m in sent["messages"]] == ["user", "assistant", "tool"]  # the tool turn survives the double translation
    assert sent["tools"][0]["function"]["name"] == "get_weather"


@respx.mock
def test_the_sdk_parses_the_stream(token, dp_app):
    respx.post(UPSTREAM).mock(return_value=httpx.Response(200, content=TEXT_LOG))
    with TestClient(dp_app) as client:
        stream = _sdk(client, token).chat.completions.create(model="gpt-test", messages=[{"role": "user", "content": "hi"}], stream=True)
        chunks = list(stream)
    text = "".join(c.choices[0].delta.content or "" for c in chunks if c.choices and c.choices[0].delta)
    assert text == "héllo \U0001f30d world"
    (usage_chunk,) = [c for c in chunks if c.usage is not None]
    assert usage_chunk.choices == []
    usage = usage_chunk.usage
    assert usage is not None
    assert (usage.prompt_tokens, usage.completion_tokens) == (5, 7)


@respx.mock
def test_what_the_gateway_dropped_is_visible_to_the_sdk_caller(token, dp_app):
    respx.post(UPSTREAM).mock(return_value=httpx.Response(200, json=TEXT_NONSTREAM))
    with TestClient(dp_app) as client:
        completion = _sdk(client, token).chat.completions.create(model="gpt-test", messages=[{"role": "user", "content": "hi"}], extra_body={"n": 2})
    gateway = (completion.model_extra or {}).get("gateway")
    assert gateway is not None
    assert [(a["param"], a["action"]) for a in gateway["adjustments"]] == [("n", "dropped")]


def test_errors_come_back_in_the_callers_dialect(token, dp_app):
    """An SDK caller's rejection is an OpenAI-shaped error, so the SDK raises its typed exception
    with the gateway's code inside, instead of choking on a foreign envelope."""
    with TestClient(dp_app) as client, pytest.raises(openai.NotFoundError) as err:
        _sdk(client, token).chat.completions.create(model="ghost", messages=[{"role": "user", "content": "hi"}])
    assert "unknown_model" in str(err.value)


@respx.mock
def test_a_canonical_caller_is_untouched_by_the_interpretation(token, dp_app):
    """The mirror invariant from INTERFACE.md: detection never changes a canonical answer."""
    respx.post(UPSTREAM).mock(return_value=httpx.Response(200, json=TEXT_NONSTREAM))
    with TestClient(dp_app) as client:
        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    body = r.json()
    assert "content" in body
    assert "choices" not in body
