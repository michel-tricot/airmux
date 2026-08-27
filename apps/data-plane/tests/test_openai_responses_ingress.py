from __future__ import annotations

import json

import pytest

from data_plane.canonical import CanonicalChunk, CanonicalMessage, DocumentPart, ReasoningDelta, ReasoningPart, TextPart, Usage
from data_plane.formats.openai_responses import input_of, json_response, messages_of
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
    return [(m.role, "".join(p.text for p in m.content if isinstance(p, TextPart))) for m in messages]


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
    response = json_response("response-1", "model-1", [], "content_filter", Usage())

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
        "response-1",
        "model-1",
        [ReasoningPart(id="rs_provider", text="thinking", signature="encrypted")],
        "stop",
        Usage(),
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

    assert messages[0].content == [DocumentPart(filename="audit.pdf", media_type="application/pdf", data="JVBERi0=")]


def test_streaming_reasoning_uses_the_provider_item_id():
    frames = ResponsesStream().chunk(CanonicalChunk(id="response-1", delta=ReasoningDelta(id="rs_provider", text="")))

    event = json.loads(frames[0].split(b"data: ", 1)[1])
    assert event["item"]["id"] == "rs_provider"
