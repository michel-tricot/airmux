from __future__ import annotations

import json
from pathlib import Path

from conftest import CTX
from jsonschema import Draft202012Validator

from data_plane.canonical import (
    CanonicalChunk,
    CanonicalReasoningDelta,
    CanonicalReasoningPart,
    CanonicalResponse,
    CanonicalTextDelta,
    CanonicalTextPart,
    CanonicalToolCallDelta,
    CanonicalToolCallPart,
    CanonicalUsage,
)
from data_plane.egress.base import CanonicalError
from data_plane.ingress.anthropic import AnthropicIngress, AnthropicResponseStream
from data_plane.ingress.openai_chat_completions import OpenAIResponseStream
from data_plane.ingress.openai_responses import ResponsesStream


def _payload(frame: bytes) -> dict:
    return json.loads(frame.split(b"data: ", 1)[1])


def test_openai_streamed_chat_preserves_an_empty_reasoning_part():
    frames = OpenAIResponseStream().chunk(CanonicalChunk(id="response-1", delta=CanonicalReasoningDelta(id="rs_1", signature="encrypted")))

    assert json.loads(frames[0].removeprefix(b"data: "))["choices"][0]["delta"]["reasoning_content"] == ""


def test_anthropic_the_stream_replays_cross_provider_reasoning_identity():
    stream = AnthropicResponseStream()
    frames = [
        *stream.chunk(CanonicalChunk(id="response-1", delta=CanonicalReasoningDelta(id="rs_provider", text="think", signature="encr"))),
        *stream.chunk(CanonicalChunk(id="response-1", delta=CanonicalReasoningDelta(signature="ypted"))),
        *stream.chunk(CanonicalChunk(id="response-1", delta=CanonicalTextDelta(text="ok"))),
    ]
    events = [json.loads(frame.split(b"data: ", 1)[1]) for frame in frames]
    signature = next(
        event["delta"]["signature"] for event in events if event["type"] == "content_block_delta" and event["delta"]["type"] == "signature_delta"
    )

    request, _ = AnthropicIngress().parse(
        {
            "model": "m",
            "max_tokens": 64,
            "messages": [{"role": "assistant", "content": [{"type": "thinking", "thinking": "think", "signature": signature}]}],
        }
    )

    assert request.messages[0].content == [CanonicalReasoningPart(id="rs_provider", text="think", signature="encrypted")]


def test_responses_streaming_reasoning_uses_the_provider_item_id():
    frames = ResponsesStream().chunk(CanonicalChunk(id="response-1", delta=CanonicalReasoningDelta(id="rs_provider", text="")))

    event = json.loads(frames[0].split(b"data: ", 1)[1])
    assert event["item"]["id"] == "rs_provider"


def test_responses_mixed_text_and_tool_streams_allocate_distinct_output_items():
    stream = ResponsesStream()
    frames = [
        *stream.chunk(CanonicalChunk(id="response-1", delta=CanonicalTextDelta(text="checking"))),
        *stream.chunk(CanonicalChunk(id="response-1", delta=CanonicalToolCallDelta(index=0, id="call-1", name="lookup", arguments="{}"))),
    ]
    payloads = [_payload(frame) for frame in frames]
    added = [payload for payload in payloads if payload["type"] == "response.output_item.added"]
    arguments = next(payload for payload in payloads if payload["type"] == "response.function_call_arguments.delta")

    assert [(payload["output_index"], payload["item"]["type"]) for payload in added] == [(0, "message"), (1, "function_call")]
    assert arguments["output_index"] == 1
    assert arguments["item_id"] == added[1]["item"]["id"]


def test_responses_responses_stream_events_carry_sequence_and_complete_item_identity():
    stream = ResponsesStream()
    start = stream.start

    frames = [
        *start(CTX),
        *stream.chunk(CanonicalChunk(id="response-1", delta=CanonicalTextDelta(text="hello"))),
        *stream.closing(
            CanonicalResponse(
                id="response-1", model="gpt-test", content=[CanonicalTextPart(text="hello")], finish_reason="stop", usage=CanonicalUsage()
            ),
            [],
        ),
    ]
    payloads = [_payload(frame) for frame in frames]

    assert [payload["sequence_number"] for payload in payloads] == list(range(len(payloads)))
    delta = next(payload for payload in payloads if payload["type"] == "response.output_text.delta")
    done = next(payload for payload in payloads if payload["type"] == "response.output_item.done")
    assert delta["item_id"] == done["item"]["id"]
    assert done["item"]["type"] == "message"
    assert done["item"]["content"] == [{"type": "output_text", "text": "hello", "annotations": [], "logprobs": []}]


def test_responses_output_events_match_the_checked_in_openai_schema():
    stream = ResponsesStream()
    frames = [
        *stream.start(CTX),
        *stream.chunk(CanonicalChunk(id="response-1", delta=CanonicalTextDelta(text="hello"))),
        *stream.chunk(CanonicalChunk(id="response-1", delta=CanonicalReasoningDelta(id="rs-1", text="think"))),
        *stream.chunk(CanonicalChunk(id="response-1", delta=CanonicalToolCallDelta(index=0, id="call-1", name="lookup", arguments="{}"))),
        *stream.closing(
            CanonicalResponse(
                id="response-1",
                model="gpt-test",
                content=[
                    CanonicalTextPart(text="hello"),
                    CanonicalReasoningPart(id="rs-1", text="think"),
                    CanonicalToolCallPart(id="call-1", name="lookup", arguments="{}"),
                ],
                finish_reason="stop",
                usage=CanonicalUsage(),
            ),
            [],
        ),
        *stream.error(CanonicalError(status=502, code="upstream_error", message="failed")),
    ]
    payloads = [_payload(frame) for frame in frames]
    schema_path = Path(__file__).parents[3] / "taxonomy/schemas/completion/oai_responses.openai.stream.json"
    validator = Draft202012Validator(json.loads(schema_path.read_text()))

    assert payloads
    for index, payload in enumerate(payloads):
        errors = [error.message for error in validator.iter_errors(payload)]
        assert not errors, (index, payload["type"], errors)
    completed = next(payload["response"] for payload in payloads if payload["type"] == "response.completed")
    assert completed["output"] == [payload["item"] for payload in payloads if payload["type"] == "response.output_item.done"]


def test_responses_streaming_response_reports_the_canonical_finish_reason():
    final = CanonicalResponse(
        id="response-1",
        model="model-1",
        content=[CanonicalTextPart(text="done")],
        finish_reason="stop",
        usage=CanonicalUsage(input_tokens=3, output_tokens=2),
    )

    terminal = ResponsesStream().closing(final, [])[-1]
    event = json.loads(terminal.split(b"data: ", 1)[1])

    assert event["response"]["gateway"]["finish_reason"] == "stop"
