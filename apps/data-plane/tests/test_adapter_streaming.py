from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from conftest import CTX, PROVIDER, TEXT_LOG, TEXT_NONSTREAM, delta_event, sse

from contract import Secret
from data_plane.egress import REGISTRY
from data_plane.egress.base import UpstreamStreamError

if TYPE_CHECKING:
    from data_plane.canonical import CanonicalChunk, CanonicalResponse

# The streaming path is a pure fold over a recorded byte log: no transport, no asyncio, no mocks.
# One recorded case per adapter kind; a new adapter joins by adding its own log here.

SPLITS = (1, 2, 3, 7, 64)

TOOL_EVENTS = [
    delta_event({"role": "assistant"}),
    delta_event({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": ""}}]}),
    delta_event({"tool_calls": [{"index": 0, "function": {"arguments": '{"ci'}}]}),
    delta_event({"tool_calls": [{"index": 1, "id": "call_2", "type": "function", "function": {"name": "search", "arguments": '{"q":"x"}'}}]}),
    delta_event({"tool_calls": [{"index": 0, "function": {"arguments": 'ty":"Paris"}'}}]}),
    delta_event({}, finish="tool_calls"),
    {"id": "chatcmpl-9", "model": "gpt-real", "choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}},
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
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'}},
                    {"id": "call_2", "type": "function", "function": {"name": "search", "arguments": '{"q":"x"}'}},
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
}


@dataclass(frozen=True)
class StreamCase:
    log: bytes
    nonstream: dict


def anthropic_sse(payload: dict) -> bytes:
    return b"event: " + payload["type"].encode() + b"\ndata: " + json.dumps(payload, ensure_ascii=False).encode() + b"\n\n"


ANTHROPIC_TEXT_EVENTS = [
    {"type": "message_start", "message": {"id": "msg_9", "usage": {"input_tokens": 5, "output_tokens": 1}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "héllo "}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "\U0001f30d wor"}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ld"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 7}},
    {"type": "message_stop"},
]
ANTHROPIC_TEXT_LOG = b"".join(anthropic_sse(e) for e in ANTHROPIC_TEXT_EVENTS)

ANTHROPIC_TEXT_NONSTREAM = {
    "id": "msg_9",
    "content": [{"type": "text", "text": "héllo \U0001f30d world"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 5, "output_tokens": 7},
}

ANTHROPIC_TOOL_EVENTS = [
    {"type": "message_start", "message": {"id": "msg_9", "usage": {"input_tokens": 9, "output_tokens": 1}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "call_1", "name": "get_weather", "input": {}}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"ci'}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": 'ty": "Paris"}'}},
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "call_2", "name": "search", "input": {}}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"q": "x"}'}},
    {"type": "content_block_stop", "index": 1},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 4}},
    {"type": "message_stop"},
]
ANTHROPIC_TOOL_LOG = b"".join(anthropic_sse(e) for e in ANTHROPIC_TOOL_EVENTS)

ANTHROPIC_TOOL_NONSTREAM = {
    "id": "msg_9",
    "content": [
        {"type": "tool_use", "id": "call_1", "name": "get_weather", "input": {"city": "Paris"}},
        {"type": "tool_use", "id": "call_2", "name": "search", "input": {"q": "x"}},
    ],
    "stop_reason": "tool_use",
    "usage": {"input_tokens": 9, "output_tokens": 4},
}

CASES: dict[str, dict[str, StreamCase]] = {
    "openai_compatible": {
        "text": StreamCase(log=TEXT_LOG, nonstream=TEXT_NONSTREAM),
        "tools": StreamCase(log=TOOL_LOG, nonstream=TOOL_NONSTREAM),
    },
    "anthropic": {
        "text": StreamCase(log=ANTHROPIC_TEXT_LOG, nonstream=ANTHROPIC_TEXT_NONSTREAM),
        "tools": StreamCase(log=ANTHROPIC_TOOL_LOG, nonstream=ANTHROPIC_TOOL_NONSTREAM),
    },
}

# A provider error arrives in each family's own spelling.
ERROR_LOGS: dict[str, bytes] = {
    "openai_compatible": sse({"error": {"code": "overloaded", "message": "try later"}}),
    "anthropic": anthropic_sse({"type": "error", "error": {"type": "overloaded", "message": "try later"}}),
}

KINDS = sorted(kind for kind in REGISTRY if kind != "openai_responses")
MODALITIES = ("text", "tools")


def test_every_registered_adapter_has_stream_cases():
    assert sorted(CASES) == KINDS


def _adapter(kind: str):
    return REGISTRY[kind](PROVIDER.model_copy(update={"kind": kind}), Secret("sk-test"))


def fold(adapter, log: bytes, size: int) -> tuple[list[CanonicalChunk], CanonicalResponse]:
    state = adapter.new_stream_state(CTX)
    chunks = [
        c for i in range(0, len(log), size) for ev in adapter.frame(log[i : i + size], state) for c in adapter.transform_stream_event(ev, state)
    ]
    return chunks, adapter.finalize(state)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("modality", MODALITIES)
@pytest.mark.parametrize("size", SPLITS)
def test_adversarial_chunk_splits_change_nothing(kind, modality, size):
    """Network byte boundaries are arbitrary; the fold must not care where they fall."""
    case = CASES[kind][modality]
    adapter = _adapter(kind)
    whole_chunks, whole_final = fold(adapter, case.log, len(case.log))
    split_chunks, split_final = fold(_adapter(kind), case.log, size)
    assert split_chunks == whole_chunks
    assert split_final == whole_final


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("modality", MODALITIES)
def test_finalize_is_valid_at_every_prefix(kind, modality):
    """Cancellation accounting calls finalize wherever the client hung up, including inside a line."""
    log = CASES[kind][modality].log
    for cut in range(len(log) + 1):
        adapter = _adapter(kind)
        state = adapter.new_stream_state(CTX)
        for ev in adapter.frame(log[:cut], state):
            adapter.transform_stream_event(ev, state)
        final = adapter.finalize(state)
        assert final.id
        assert final.usage.input_tokens >= 0
        assert final.usage.output_tokens >= 0


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("modality", MODALITIES)
def test_stream_and_buffered_agree(kind, modality):
    """One conversation, two transports, the same canonical response."""
    case = CASES[kind][modality]
    adapter = _adapter(kind)
    _, streamed = fold(adapter, case.log, 7)
    buffered = adapter.transform_response(json.dumps(case.nonstream).encode(), CTX)
    assert streamed.content == buffered.content
    assert streamed.finish_reason == buffered.finish_reason
    assert streamed.usage == buffered.usage


@pytest.mark.parametrize("kind", KINDS)
def test_a_stream_truncated_before_its_terminal_event_is_rejected(kind):
    adapter = _adapter(kind)
    state = adapter.new_stream_state(CTX)
    for event in adapter.frame(CASES[kind]["text"].log[:-1], state):
        adapter.transform_stream_event(event, state)
    with pytest.raises(ValueError, match="ended before"):
        adapter.validate_stream(state)


@pytest.mark.parametrize("kind", KINDS)
def test_a_complete_stream_passes_validation(kind):
    adapter = _adapter(kind)
    state = adapter.new_stream_state(CTX)
    for event in adapter.frame(CASES[kind]["text"].log, state):
        adapter.transform_stream_event(event, state)
    adapter.validate_stream(state)


@pytest.mark.parametrize("kind", KINDS)
def test_a_terminal_marker_without_a_completed_response_is_rejected(kind):
    adapter = _adapter(kind)
    state = adapter.new_stream_state(CTX)
    events = list(adapter.frame(CASES[kind]["text"].log, state))
    for event in events[-1:]:
        adapter.transform_stream_event(event, state)
    with pytest.raises(ValueError, match="ended before"):
        adapter.validate_stream(state)


@pytest.mark.parametrize("kind", KINDS)
def test_a_malformed_stream_event_is_rejected(kind):
    adapter = _adapter(kind)
    state = adapter.new_stream_state(CTX)
    (event,) = list(adapter.frame(b"data: not-json\n\n", state))
    with pytest.raises(ValueError, match="invalid upstream stream event"):
        adapter.transform_stream_event(event, state)


@pytest.mark.parametrize("kind", KINDS)
def test_an_empty_buffered_provider_response_is_rejected(kind):
    with pytest.raises(ValueError, match="invalid upstream response"):
        _adapter(kind).transform_response(b"{}", CTX)


@pytest.mark.parametrize("kind", KINDS)
def test_tool_call_fragments_reassemble_with_valid_json(kind):
    adapter = _adapter(kind)
    chunks, final = fold(adapter, CASES[kind]["tools"].log, 3)
    calls = [part for part in final.content if part.type == "tool_call"]
    assert [(call.id, call.name) for call in calls] == [("call_1", "get_weather"), ("call_2", "search")]
    for call in calls:
        json.loads(call.arguments)
    openers = [c.delta for c in chunks if c.delta is not None and c.delta.type == "tool_call" and c.delta.id]
    assert {(d.index, d.id) for d in openers} == {(0, "call_1"), (1, "call_2")}


@pytest.mark.parametrize("kind", KINDS)
def test_a_mid_stream_error_event_raises(kind):
    adapter = _adapter(kind)
    state = adapter.new_stream_state(CTX)
    (event,) = list(adapter.frame(ERROR_LOGS[kind], state))
    with pytest.raises(UpstreamStreamError) as err:
        adapter.transform_stream_event(event, state)
    assert err.value.code == "overloaded"


def test_usage_reported_in_an_unknown_shape_reads_as_estimated():
    """A provider reporting usage the adapter cannot recognize must never meter as free."""
    adapter = _adapter("openai_compatible")
    body = dict(TEXT_NONSTREAM, usage={"total_billing_units": 14})
    response = adapter.transform_response(json.dumps(body).encode(), CTX)
    assert response.usage.estimated


ANTHROPIC_THINKING_EVENTS = [
    {"type": "message_start", "message": {"id": "msg_9", "usage": {"input_tokens": 5, "output_tokens": 1}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "think "}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hard"}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig_1"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "done"}},
    {"type": "content_block_stop", "index": 1},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 9}},
    {"type": "message_stop"},
]


def test_the_thinking_signature_survives_the_stream():
    """A signature the provider issues must come back on the reasoning part: a later turn
    without it is rejected, so losing it in the fold breaks multi-turn reasoning."""
    adapter = _adapter("anthropic")
    log = b"".join(anthropic_sse(e) for e in ANTHROPIC_THINKING_EVENTS)
    chunks, final = fold(adapter, log, 7)
    (reasoning, text) = final.content
    assert reasoning.type == "reasoning"
    assert (reasoning.text, reasoning.signature) == ("think hard", "sig_1")
    assert text.type == "text"
    signatures = [c.delta.signature for c in chunks if c.delta is not None and c.delta.type == "reasoning" and c.delta.signature]
    assert signatures == ["sig_1"]


def test_a_cancel_before_the_final_usage_reads_as_estimated():
    """message_delta carries the real output count; a disconnect before it must meter as an
    estimate, never as an authoritative zero."""
    adapter = _adapter("anthropic")
    log = b"".join(anthropic_sse(e) for e in ANTHROPIC_TEXT_EVENTS[:5])  # cut before message_delta
    _, final = fold(adapter, log, 7)
    assert final.usage.estimated
