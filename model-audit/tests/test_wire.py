from __future__ import annotations

from model_audit.drivers.wire import anthropic_body
from model_audit.models import Request
from tests.helpers import case


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
