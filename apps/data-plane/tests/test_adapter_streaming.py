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


CASES: dict[str, dict[str, StreamCase]] = {
    "openai_compatible": {
        "text": StreamCase(log=TEXT_LOG, nonstream=TEXT_NONSTREAM),
        "tools": StreamCase(log=TOOL_LOG, nonstream=TOOL_NONSTREAM),
    },
}

KINDS = sorted(REGISTRY)
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
    log = sse({"error": {"code": "overloaded", "message": "try later"}})
    (event,) = list(adapter.frame(log, state))
    with pytest.raises(UpstreamStreamError) as err:
        adapter.transform_stream_event(event, state)
    assert err.value.code == "overloaded"


def test_usage_reported_in_an_unknown_shape_reads_as_estimated():
    """A provider reporting usage the adapter cannot recognize must never meter as free."""
    adapter = _adapter("openai_compatible")
    body = dict(TEXT_NONSTREAM, usage={"total_billing_units": 14})
    response = adapter.transform_response(json.dumps(body).encode(), CTX)
    assert response.usage.estimated
