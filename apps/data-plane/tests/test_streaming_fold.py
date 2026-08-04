from __future__ import annotations

import json

import pytest
from conftest import CTX, TEXT_EVENTS, TEXT_LOG, TEXT_NONSTREAM, USAGE, delta_event, make_adapter, sse

from data_plane.canonical import UpstreamStreamError

TOOL_EVENTS = [
    delta_event({"role": "assistant"}),
    delta_event({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": ""}}]}),
    delta_event({"tool_calls": [{"index": 0, "function": {"arguments": '{"cit'}}]}),
    delta_event({"tool_calls": [{"index": 0, "function": {"arguments": 'y": "Paris"}'}}]}),
    delta_event({}, finish="tool_calls"),
    {"id": "chatcmpl-9", "model": "gpt-real", "choices": [], "usage": USAGE},
]
TOOL_LOG = b"".join(sse(e) for e in TOOL_EVENTS) + b"data: [DONE]\n\n"

TOOL_NONSTREAM = {
    "id": "chatcmpl-9",
    "model": "gpt-real",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'}}],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "usage": USAGE,
}


def fold(raw: bytes, chunk_size: int):
    adapter = make_adapter()
    state = adapter.new_stream_state(CTX)
    chunks = []
    for start in range(0, len(raw), chunk_size):
        for ev in adapter.frame(raw[start : start + chunk_size], state):
            chunks.extend(adapter.transform_stream_event(ev, state))
    return chunks, adapter.finalize(state)


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 64, len(TEXT_LOG)])
def test_fold_is_invariant_under_adversarial_splits(chunk_size):
    chunks, response = fold(TEXT_LOG, chunk_size)
    assert "".join(c.delta["text"] for c in chunks if c.delta.get("type") == "text") == "héllo \U0001f30d world"
    assert response == fold(TEXT_LOG, len(TEXT_LOG))[1]


@pytest.mark.parametrize(("log", "nonstream"), [(TEXT_LOG, TEXT_NONSTREAM), (TOOL_LOG, TOOL_NONSTREAM)])
def test_stream_and_nonstream_agree(log, nonstream):
    _, streamed = fold(log, 7)
    direct = make_adapter().transform_response(json.dumps(nonstream).encode(), CTX)
    assert streamed == direct


def test_finalize_is_valid_at_every_prefix():
    adapter = make_adapter()
    for cut in range(len(TEXT_EVENTS) + 1):
        state = adapter.new_stream_state(CTX)
        log = b"".join(sse(e) for e in TEXT_EVENTS[:cut])
        for ev in adapter.frame(log, state):
            adapter.transform_stream_event(ev, state)
        response = adapter.finalize(state)
        assert response.model == "gpt-test"
        assert response.usage.estimated == (cut < len(TEXT_EVENTS))
        if cut < len(TEXT_EVENTS):
            assert response.usage.input_tokens == 0
    full = adapter.finalize(state)
    assert full.usage.input_tokens == 5
    assert full.usage.output_tokens == 7


def test_mid_stream_error_raises_and_maps():
    adapter = make_adapter()
    state = adapter.new_stream_state(CTX)
    log = sse(TEXT_EVENTS[1]) + sse({"error": {"code": "overloaded", "message": "try later"}})
    events = list(adapter.frame(log, state))
    adapter.transform_stream_event(events[0], state)
    with pytest.raises(UpstreamStreamError) as excinfo:
        adapter.transform_stream_event(events[1], state)
    err = adapter.map_error(excinfo.value)
    assert err.status == 502
    assert err.code == "overloaded"
    partial = adapter.finalize(state)
    assert partial.content == [{"type": "text", "text": "héllo "}]


def test_tool_call_fragments_concatenate():
    _, response = fold(TOOL_LOG, 3)
    (tool,) = response.content
    assert tool["function"]["name"] == "get_weather"
    assert json.loads(tool["function"]["arguments"]) == {"city": "Paris"}


REASONING_EVENTS = [
    delta_event({"role": "assistant"}),
    delta_event({"reasoning_content": "The user wants "}),
    delta_event({"reasoning_content": "a sum: 2+2=4."}),
    delta_event({"content": "The answer "}),
    delta_event({"content": "is 4."}),
    delta_event({}, finish="stop"),
    {"id": "chatcmpl-9", "model": "gpt-real", "choices": [], "usage": USAGE},
]
REASONING_LOG = b"".join(sse(e) for e in REASONING_EVENTS) + b"data: [DONE]\n\n"

REASONING_NONSTREAM = {
    "id": "chatcmpl-9",
    "model": "gpt-real",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "reasoning_content": "The user wants a sum: 2+2=4.", "content": "The answer is 4."},
            "finish_reason": "stop",
        }
    ],
    "usage": USAGE,
}


@pytest.mark.parametrize("chunk_size", [1, 7, len(REASONING_LOG)])
def test_reasoning_streams_and_agrees(chunk_size):
    chunks, response = fold(REASONING_LOG, chunk_size)
    reasoning = "".join(c.delta["text"] for c in chunks if c.delta.get("type") == "reasoning")
    assert reasoning == "The user wants a sum: 2+2=4."
    assert response.content[0] == {"type": "reasoning", "text": "The user wants a sum: 2+2=4."}
    assert response.content[1] == {"type": "text", "text": "The answer is 4."}
    direct = make_adapter().transform_response(json.dumps(REASONING_NONSTREAM).encode(), CTX)
    assert response == direct
