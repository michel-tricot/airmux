from __future__ import annotations

import json

import httpx
import respx
from conformance import make_ctx
from starlette.testclient import TestClient

from data_plane.app import app
from data_plane.canonical import CanonicalChunk, CanonicalResponse, Usage
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
    assert body["usage"] == {"input_tokens": 5, "output_tokens": 7}


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
    assert body["usage"] == {"input_tokens": 5, "output_tokens": 2}


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
