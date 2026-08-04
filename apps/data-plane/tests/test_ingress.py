from __future__ import annotations

import json

import httpx
import respx
from conformance import make_ctx
from conftest import MODEL
from starlette.testclient import TestClient

from data_plane.adapters import REGISTRY
from data_plane.app import app
from data_plane.canonical import CanonicalChunk, CanonicalRequest, CanonicalResponse, Usage
from data_plane.ingress import ANTHROPIC

# --- upstream fixtures (what the provider returns) ---

OPENAI_REPLY = {
    "id": "cmpl-1",
    "model": "gpt-real",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello there"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
}


def test_parse_hoists_system_and_converts_tools():
    body = json.dumps(
        {
            "model": "claude",
            "system": "be terse",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hi "}, {"type": "text", "text": "there"}]}],
            "tools": [{"name": "f", "description": "d", "input_schema": {"type": "object"}}],
        }
    ).encode()
    req = ANTHROPIC.parse(body)
    assert req.messages[0] == {"role": "system", "content": "be terse"}
    assert req.messages[1] == {"role": "user", "content": "hi there"}  # text blocks collapsed to a string
    assert req.max_tokens == 100
    assert req.tools == [{"type": "function", "function": {"name": "f", "description": "d", "parameters": {"type": "object"}}}]


def test_render_response_is_anthropic_shaped():
    final = CanonicalResponse(
        id="msg_1",
        model="claude",
        content=[{"type": "text", "text": "hi"}, {"type": "tool_call", "id": "t1", "function": {"name": "f", "arguments": '{"a": 1}'}}],
        finish_reason="tool_calls",
        usage=Usage(input_tokens=5, output_tokens=7),
    )
    body = json.loads(bytes(ANTHROPIC.render_response(final).body))
    assert body["type"] == "message"
    assert body["role"] == "assistant"
    assert body["stop_reason"] == "tool_use"
    assert body["content"] == [{"type": "text", "text": "hi"}, {"type": "tool_use", "id": "t1", "name": "f", "input": {"a": 1}}]
    assert body["usage"] == {"input_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 7}


def test_egress_stream_is_a_valid_anthropic_sequence():
    egress = ANTHROPIC.new_egress()
    ctx = make_ctx("anthropic")
    events: list[bytes] = []
    events += egress.start(ctx)
    events += egress.chunk(CanonicalChunk(id="x", delta={"type": "text", "text": "Hel"}))
    events += egress.chunk(CanonicalChunk(id="x", delta={"type": "text", "text": "lo"}))
    events += egress.finish(CanonicalResponse(id="x", model="claude", content=[], finish_reason="stop", usage=Usage(input_tokens=5, output_tokens=2)))
    names = [line[len("event: ") :] for blob in events for line in blob.decode().splitlines() if line.startswith("event: ")]
    assert names[0] == "message_start"
    assert names.count("content_block_start") == 1
    assert names.count("content_block_delta") == 2
    assert names[-2:] == ["message_delta", "message_stop"]
    text = "".join(
        json.loads(line[len("data: ") :])["delta"]["text"]
        for blob in events
        for line in blob.decode().splitlines()
        if line.startswith("data: ") and '"text_delta"' in line
    )
    assert text == "Hello"


@respx.mock
def test_messages_endpoint_end_to_end_over_openai_provider(token):
    """A client uses the Anthropic Messages surface; the model routes to an OpenAI provider."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=OPENAI_REPLY))
    with TestClient(app) as client:
        r = client.post(
            "/v1/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "gpt-test", "max_tokens": 50, "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "message"
    assert body["content"] == [{"type": "text", "text": "hello there"}]
    assert body["stop_reason"] == "end_turn"
    assert body["usage"] == {"input_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 2}


@respx.mock
def test_messages_endpoint_streaming_over_openai_provider(token):
    log = (
        b'data: {"id":"cmpl-1","choices":[{"index":0,"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
        b'data: {"id":"cmpl-1","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
        b'data: {"id":"cmpl-1","choices":[],"usage":{"prompt_tokens":5,"completion_tokens":1}}\n\n'
        b"data: [DONE]\n\n"
    )
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=log))
    with (
        TestClient(app) as client,
        client.stream(
            "POST",
            "/v1/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "gpt-test", "max_tokens": 50, "stream": True, "messages": [{"role": "user", "content": "hi"}]},
        ) as r,
    ):
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode()
    names = [line[len("event: ") :] for line in body.splitlines() if line.startswith("event: ")]
    assert names[0] == "message_start"
    assert "content_block_delta" in names
    assert names[-1] == "message_stop"
    text = "".join(
        json.loads(line[len("data: ") :])["delta"]["text"] for line in body.splitlines() if line.startswith("data: ") and '"text_delta"' in line
    )
    assert text == "Hi"


def test_max_tokens_clamped_to_model_output_limit():
    from data_plane.normalize import normalize_request  # noqa: PLC0415

    provider = make_ctx("openai_compatible").provider
    capped = MODEL.model_copy(update={"max_output_tokens": 16384})
    over = CanonicalRequest(model="m", messages=[], max_tokens=32000)
    assert normalize_request(over, capped, provider).max_tokens == 16384
    assert normalize_request(CanonicalRequest(model="m", messages=[], max_tokens=100), capped, provider).max_tokens == 100
    assert normalize_request(over, MODEL, provider).max_tokens == 32000  # no cap known -> no clamp
    assert normalize_request(CanonicalRequest(model="m", messages=[]), capped, provider).max_tokens is None


def test_cache_control_survives_ingress_to_anthropic_upstream(monkeypatch):
    """Claude Code's cache markers on system and tools must reach the Anthropic upstream request."""
    monkeypatch.setenv("K", "sk-ant")
    body = json.dumps(
        {
            "model": "claude",
            "max_tokens": 100,
            "system": [{"type": "text", "text": "big prompt", "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"name": "f", "input_schema": {"type": "object"}, "cache_control": {"type": "ephemeral"}}],
        }
    ).encode()
    req = ANTHROPIC.parse(body)
    adapter = REGISTRY["anthropic"](make_ctx("anthropic").provider)
    up = json.loads(adapter.transform_request(req, make_ctx("anthropic").model).body)
    assert up["system"] == [{"type": "text", "text": "big prompt", "cache_control": {"type": "ephemeral"}}]
    assert up["tools"][0]["cache_control"] == {"type": "ephemeral"}


def test_cache_control_stripped_for_openai_upstream(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    body = json.dumps(
        {
            "model": "gpt",
            "max_tokens": 100,
            "system": [{"type": "text", "text": "prompt", "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"name": "f", "input_schema": {"type": "object"}, "cache_control": {"type": "ephemeral"}}],
        }
    ).encode()
    req = ANTHROPIC.parse(body)
    adapter = REGISTRY["openai_compatible"](make_ctx("openai_compatible").provider)
    up = json.loads(adapter.transform_request(req, make_ctx("openai_compatible").model).body)
    assert "cache_control" not in json.dumps(up)


def test_anthropic_usage_counts_cache_tokens():
    adapter = REGISTRY["anthropic"](make_ctx("anthropic").provider)
    reply = json.dumps(
        {
            "id": "msg",
            "model": "claude",
            "content": [{"type": "text", "text": "hi"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 4, "cache_read_input_tokens": 30000, "cache_creation_input_tokens": 0, "output_tokens": 6},
        }
    ).encode()
    resp = adapter.transform_response(reply, make_ctx("anthropic"))
    assert resp.usage.input_tokens == 30004  # cache-read tokens are still prompt tokens


def test_anthropic_directive_blocks_stripped_from_system():
    """A per-request x-anthropic-* metadata block must not reach the canonical prompt."""
    body = json.dumps(
        {
            "model": "m",
            "max_tokens": 10,
            "system": [
                {"type": "text", "text": "x-anthropic-billing-header: cc_version=2.1; cch=abc123;"},
                {"type": "text", "text": "You are helpful.", "cache_control": {"type": "ephemeral"}},
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }
    ).encode()
    req = ANTHROPIC.parse(body)
    system = req.messages[0]
    assert system["role"] == "system"
    texts = [b["text"] for b in system["content"]]
    assert texts == ["You are helpful."]  # directive dropped, real content and its cache_control kept
    assert system["content"][0]["cache_control"] == {"type": "ephemeral"}
