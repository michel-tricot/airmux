from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import CTX
from jsonschema import Draft202012Validator

from data_plane.canonical import (
    CanonicalChunk,
    CanonicalDocumentPart,
    CanonicalMessage,
    CanonicalReasoningDelta,
    CanonicalReasoningPart,
    CanonicalResponse,
    CanonicalTextDelta,
    CanonicalTextPart,
    CanonicalToolCallDelta,
    CanonicalUsage,
)
from data_plane.egress.base import CanonicalError
from data_plane.formats.openai_responses import ResponseMetadata, input_of, json_response, messages_of
from data_plane.ingress.openai_responses import OpenAIResponsesIngress, ResponsesStream

SPELLINGS = [
    (
        "typed input parts",
        [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
        [("user", "hi")],
    ),
    (
        "assistant history as a bare string, the only form Responses takes for it",
        [{"type": "message", "role": "assistant", "content": "Paris"}],
        [("assistant", "Paris")],
    ),
    (
        "user text as a bare string",
        [{"type": "message", "role": "user", "content": "hi"}],
        [("user", "hi")],
    ),
    (
        "no type field, which EasyInputMessage makes optional and the SDKs omit",
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Paris"}],
        [("user", "hi"), ("assistant", "Paris")],
    ),
    (
        "developer role, which canonical folds into system",
        [{"role": "developer", "content": "be terse"}],
        [("system", "be terse")],
    ),
    (
        "assistant echoed back in the output spelling",
        [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Paris"}]}],
        [("assistant", "Paris")],
    ),
]


def _said(messages: list[CanonicalMessage]) -> list[tuple[str, str]]:
    return [(m.role, "".join(p.text for p in m.content if isinstance(p, CanonicalTextPart))) for m in messages]


@pytest.mark.parametrize(("items", "expected"), [(i, e) for _, i, e in SPELLINGS], ids=[n for n, _, _ in SPELLINGS])
def test_every_documented_input_spelling_survives_the_read(items, expected):
    assert _said(messages_of(items)) == expected


def test_a_conversation_read_then_rewritten_keeps_every_turn():
    original = [
        {"role": "user", "content": "What is the capital of France?"},
        {"role": "assistant", "content": "Paris"},
        {"role": "user", "content": "And of Spain?"},
    ]
    assert _said(messages_of(input_of(messages_of(original)))) == [
        ("user", "What is the capital of France?"),
        ("assistant", "Paris"),
        ("user", "And of Spain?"),
    ]


def test_content_filter_is_visible_in_a_responses_reply():
    response = json_response(ResponseMetadata("response-1", "model-1", 1), [], "content_filter", CanonicalUsage())

    assert response["status"] == "incomplete"
    assert response["incomplete_details"] == {"reason": "content_filter"}


def test_json_schema_format_is_translated_into_canonical():
    request, _ = OpenAIResponsesIngress().parse(
        {
            "model": "gpt-test",
            "input": "answer with JSON",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "answer",
                    "strict": True,
                    "schema": {"type": "object", "properties": {"answer": {"type": "integer"}}},
                }
            },
        }
    )

    assert request.response_format is not None
    assert request.response_format.type == "json_schema"
    assert request.response_format.json_schema == {
        "name": "answer",
        "strict": True,
        "schema": {"type": "object", "properties": {"answer": {"type": "integer"}}},
    }


def test_reasoning_configuration_is_translated_into_canonical():
    request, _ = OpenAIResponsesIngress().parse(
        {
            "model": "gpt-test",
            "input": "reason",
            "reasoning": {"effort": "low", "summary": "auto"},
        }
    )

    assert request.reasoning is not None
    assert request.reasoning.effort == "low"
    assert request.reasoning.summary == "auto"


def test_reasoning_response_preserves_the_provider_item_id():
    response = json_response(
        ResponseMetadata("response-1", "model-1", 1),
        [CanonicalReasoningPart(id="rs_provider", text="thinking", signature="encrypted")],
        "stop",
        CanonicalUsage(),
    )

    assert response["output"][0]["id"] == "rs_provider"


def test_input_file_is_preserved_as_a_document():
    messages = messages_of(
        [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "filename": "audit.pdf",
                        "file_data": "data:application/pdf;base64,JVBERi0=",
                    }
                ],
            }
        ]
    )

    assert messages[0].content == [CanonicalDocumentPart(filename="audit.pdf", media_type="application/pdf", data="JVBERi0=")]


def test_streaming_reasoning_uses_the_provider_item_id():
    frames = ResponsesStream().chunk(CanonicalChunk(id="response-1", delta=CanonicalReasoningDelta(id="rs_provider", text="")))

    event = json.loads(frames[0].split(b"data: ", 1)[1])
    assert event["item"]["id"] == "rs_provider"


def _payload(frame: bytes) -> dict:
    return json.loads(frame.split(b"data: ", 1)[1])


def test_mixed_text_and_tool_streams_allocate_distinct_output_items():
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


def test_responses_stream_events_carry_sequence_and_complete_item_identity():
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
    assert done["item"]["content"] == [{"type": "output_text", "text": "hello", "annotations": []}]


def test_responses_output_events_match_the_checked_in_openai_schema():
    stream = ResponsesStream()
    frames = [
        *stream.start(CTX),
        *stream.chunk(CanonicalChunk(id="response-1", delta=CanonicalTextDelta(text="hello"))),
        *stream.chunk(CanonicalChunk(id="response-1", delta=CanonicalReasoningDelta(id="rs-1", text="think"))),
        *stream.chunk(CanonicalChunk(id="response-1", delta=CanonicalToolCallDelta(index=0, id="call-1", name="lookup", arguments="{}"))),
        *stream.closing(CanonicalResponse(id="response-1", model="gpt-test", content=[], finish_reason="stop", usage=CanonicalUsage()), []),
        *stream.error(CanonicalError(status=502, code="upstream_error", message="failed")),
    ]
    payloads = [_payload(frame) for frame in frames]
    schema_path = Path(__file__).parents[3] / "taxonomy/schemas/completion/oai_responses.openai.stream.json"
    validator = Draft202012Validator(json.loads(schema_path.read_text()))

    errors = {payload["type"]: [error.message for error in validator.iter_errors(payload)] for payload in payloads}

    assert errors
    assert not any(errors.values()), errors


def test_streaming_response_reports_the_canonical_finish_reason():
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
