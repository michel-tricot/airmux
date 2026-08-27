from __future__ import annotations

from model_audit.drivers.wire import anthropic_body, openai_messages
from model_audit.models import Request
from tests.helpers import case


def test_openai_chat_maps_inline_pdf_to_a_file_content_part():
    request = Request(
        messages=(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Read the PDF"},
                    {"type": "document", "media_type": "application/pdf", "data": "cGRm"},
                ],
            },
        )
    )

    messages = openai_messages(case(request=request), responses=False)

    assert messages[0]["content"] == [
        {"type": "text", "text": "Read the PDF"},
        {
            "type": "file",
            "file": {
                "filename": "audit.pdf",
                "file_data": "data:application/pdf;base64,cGRm",
            },
        },
    ]


def test_anthropic_maps_json_schema_output_to_output_config():
    request = Request(
        messages=({"role": "user", "content": "Return JSON"},),
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "answer",
                "strict": True,
                "schema": {"type": "object", "properties": {"answer": {"type": "integer"}}},
            },
        },
        reasoning={"type": "adaptive", "effort": "low"},
    )

    body = anthropic_body("model", case(request=request), "buffered")

    assert body["output_config"] == {
        "effort": "low",
        "format": {
            "type": "json_schema",
            "schema": {"type": "object", "properties": {"answer": {"type": "integer"}}},
        },
    }


def test_anthropic_maps_json_object_output_to_an_unconstrained_object_schema():
    request = Request(
        messages=({"role": "user", "content": "Return JSON"},),
        response_format={"type": "json_object"},
    )

    body = anthropic_body("model", case(request=request), "buffered")

    assert body["output_config"] == {"format": {"type": "json_schema", "schema": {"type": "object"}}}
