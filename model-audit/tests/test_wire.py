from __future__ import annotations

import json
from pathlib import Path

from model_audit.cases import load_cases, load_features
from model_audit.drivers.wire import anthropic_body, body_of, openai_messages
from model_audit.models import Request
from tests.helpers import case

ROOT = Path(__file__).resolve().parents[1]


def test_every_case_compiles_to_json_for_each_applicable_wire_surface():
    cases = load_cases(ROOT / "cases", load_features(ROOT / "definitions" / "features.yml"))
    all_endpoints = {"chat/completions", "responses", "messages"}

    payloads = [
        body_of(endpoint, "model", audit_case, transport)
        for audit_case in cases
        for endpoint in audit_case.applies_to.endpoints or all_endpoints
        for transport in audit_case.transports
    ]

    assert all(json.loads(json.dumps(payload)) == payload for payload in payloads)


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
