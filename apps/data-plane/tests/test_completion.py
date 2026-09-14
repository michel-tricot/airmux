from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from corpus import CORPUS, request_of
from pydantic import TypeAdapter, ValidationError

from data_plane.canonical import (
    CanonicalAdjustment,
    CanonicalChunk,
    CanonicalDocumentPart,
    CanonicalGatewayInfo,
    CanonicalImagePart,
    CanonicalMessage,
    CanonicalReasoningDelta,
    CanonicalReasoningPart,
    CanonicalRequest,
    CanonicalResponse,
    CanonicalTextDelta,
    CanonicalTextPart,
    CanonicalToolCallDelta,
    CanonicalToolCallPart,
    CanonicalToolResultPart,
    CanonicalUsage,
    json_schemas,
)

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "taxonomy" / "schemas" / "completion"


@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c.name)
def test_every_corpus_request_survives_a_json_round_trip(case):
    request = request_of(case)
    assert CanonicalRequest.model_validate_json(request.model_dump_json()) == request


def test_the_corpus_reaches_every_part_type():
    """The corpus is the shared fixture of the rebuild; a part type it never exercises is untested everywhere downstream."""
    reached = {part.type for case in CORPUS for message in case.messages for part in message.content}
    assert reached == {"text", "image", "document", "reasoning", "tool_call", "tool_result"}


@pytest.mark.parametrize(
    ("role", "part"),
    [
        ("system", CanonicalImagePart(url="https://example.com/cat.png")),
        ("system", CanonicalDocumentPart(url="https://example.com/report.pdf")),
        ("system", CanonicalToolCallPart(id="c1", name="f", arguments="{}")),
        ("user", CanonicalToolCallPart(id="c1", name="f", arguments="{}")),
        ("user", CanonicalReasoningPart(text="hm")),
        ("assistant", CanonicalToolResultPart(call_id="c1", content=[CanonicalTextPart(text="out")])),
        ("assistant", CanonicalImagePart(url="https://example.com/cat.png")),
        ("assistant", CanonicalDocumentPart(url="https://example.com/report.pdf")),
    ],
)
def test_a_part_outside_its_role_is_rejected(role, part):
    with pytest.raises(ValidationError):
        TypeAdapter(CanonicalMessage).validate_python({"role": role, "content": [part]})


def test_an_image_needs_exactly_one_source():
    with pytest.raises(ValidationError, match="exactly one"):
        CanonicalImagePart(url="https://example.com/cat.png", data="iVBORw0KGgo=", media_type="image/png")
    with pytest.raises(ValidationError, match="exactly one"):
        CanonicalImagePart(media_type="image/png")
    with pytest.raises(ValidationError, match="media_type"):
        CanonicalImagePart(data="iVBORw0KGgo=")


def test_a_document_needs_exactly_one_source():
    with pytest.raises(ValidationError, match="exactly one"):
        CanonicalDocumentPart(url="https://example.com/report.pdf", data="JVBERi0=", media_type="application/pdf")
    with pytest.raises(ValidationError, match="exactly one"):
        CanonicalDocumentPart(media_type="application/pdf")
    with pytest.raises(ValidationError, match="media_type"):
        CanonicalDocumentPart(data="JVBERi0=")


def test_tool_arguments_stay_json_text():
    """Parsing would lose a truncated stream's partial arguments and reorder the provider's keys."""
    calls = [part for case in CORPUS for message in case.messages for part in message.content if part.type == "tool_call"]
    assert calls
    for call in calls:
        assert isinstance(call.arguments, str)
        json.loads(call.arguments)


def test_a_response_carries_assistant_parts_only():
    with pytest.raises(ValidationError):
        CanonicalResponse.model_validate(
            {
                "id": "r1",
                "model": "m",
                "content": [{"type": "tool_result", "call_id": "c1", "content": [{"type": "text", "text": "out"}]}],
                "finish_reason": "stop",
                "usage": {},
            }
        )


def test_an_unknown_request_field_is_kept_for_forwarding():
    """A caller who swapped a provider's base URL for the gateway may carry fields the core does not
    model; rejecting them would break the swap, dropping them silently would break trust."""
    body = {"model": "m", "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}], "frequency_penalty": 0.5}
    request = CanonicalRequest.model_validate(body)
    assert request.extra == {"frequency_penalty": 0.5}
    assert CanonicalRequest.model_validate_json(request.model_dump_json()) == request


def test_string_content_is_shorthand_for_one_text_part():
    """The wire accepts the shorthand; the model only ever holds the typed form."""
    message = TypeAdapter(CanonicalMessage).validate_python({"role": "user", "content": "hi"})
    assert message.content == [CanonicalTextPart(text="hi")]
    result = CanonicalToolResultPart.model_validate({"type": "tool_result", "call_id": "c1", "content": "18C, light rain"})
    assert result.content == [CanonicalTextPart(text="18C, light rain")]
    assert '"content":[{' in message.model_dump_json(exclude_none=True)


def test_an_unknown_field_inside_a_part_is_rejected():
    """Nested shapes are restructured in translation, so an unknown field there has nothing faithful to forward."""
    with pytest.raises(ValidationError, match="glow"):
        CanonicalTextPart.model_validate({"type": "text", "text": "hi", "glow": True})


def test_response_format_states_are_structural():
    body = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    with pytest.raises(ValidationError):
        CanonicalRequest.model_validate({**body, "response_format": {"type": "json_schema"}})
    with pytest.raises(ValidationError):
        CanonicalRequest.model_validate({**body, "response_format": {"type": "text", "json_schema": {"type": "object"}}})


def test_request_schema_exposes_role_specific_messages():
    message_schema = CanonicalRequest.model_json_schema()["properties"]["messages"]["items"]
    assert message_schema["discriminator"]["propertyName"] == "role"
    assert len(message_schema["oneOf"]) == 3


def test_what_the_gateway_did_is_reported_under_its_own_field():
    """Data plane internals reach the caller through one namespaced envelope; the rest of the
    response stays about the completion."""
    response = CanonicalResponse(
        id="r1",
        model="m",
        content=[CanonicalTextPart(text="ok")],
        finish_reason="stop",
        usage=CanonicalUsage(),
        gateway=CanonicalGatewayInfo(
            finish_reason="stop",
            adjustments=[CanonicalAdjustment(param="logit_bias", action="dropped", detail="upstream does not accept it")],
        ),
    )
    assert CanonicalResponse.model_validate_json(response.model_dump_json()) == response
    bare = CanonicalResponse(id="r2", model="m", content=[CanonicalTextPart(text="ok")], finish_reason="stop", usage=CanonicalUsage())
    assert bare.gateway == CanonicalGatewayInfo()


def test_the_definition_is_frozen():
    request = request_of(CORPUS[0])
    with pytest.raises(ValidationError):
        setattr(request, "model", "other")  # noqa: B010 a static assignment would be rejected by the type checker, which is the point


def test_a_stream_of_typed_deltas_reassembles_the_response():
    """The stream face and the response face describe the same conversation: folding one yields the other."""
    chunks = [
        CanonicalChunk(id="r1", delta=CanonicalReasoningDelta(text="think ")),
        CanonicalChunk(id="r1", delta=CanonicalReasoningDelta(text="hard", signature="sig_1")),
        CanonicalChunk(id="r1", delta=CanonicalTextDelta(text="hé")),
        CanonicalChunk(id="r1", delta=CanonicalTextDelta(text="llo")),
        CanonicalChunk(id="r1", delta=CanonicalToolCallDelta(index=0, id="call_1", name="get_weather", arguments='{"ci')),
        CanonicalChunk(id="r1", delta=CanonicalToolCallDelta(index=0, arguments='ty":"Paris"}')),
        CanonicalChunk(id="r1", finish_reason="tool_calls", usage=CanonicalUsage(input_tokens=5, output_tokens=7)),
    ]

    reasoning_text = "".join(c.delta.text for c in chunks if c.delta is not None and c.delta.type == "reasoning")
    signature = next(c.delta.signature for c in chunks if c.delta is not None and c.delta.type == "reasoning" and c.delta.signature)
    text = "".join(c.delta.text for c in chunks if c.delta is not None and c.delta.type == "text")
    calls = [c.delta for c in chunks if c.delta is not None and c.delta.type == "tool_call"]
    arguments = "".join(d.arguments for d in calls if d.index == 0)
    opener = next(d for d in calls if d.id is not None)
    closing = next(c for c in chunks if c.finish_reason is not None)

    assert reasoning_text == "think hard"
    assert signature == "sig_1"
    assert text == "héllo"
    assert json.loads(arguments) == {"city": "Paris"}
    assert (opener.id, opener.name) == ("call_1", "get_weather")
    assert closing.delta is None
    assert closing.usage == CanonicalUsage(input_tokens=5, output_tokens=7)


@pytest.mark.parametrize("face", ["request", "response", "stream"])
def test_the_committed_schema_matches_the_definition(face):
    """taxonomy/schemas/completion is the published word on what the gateway accepts and emits;
    scripts/export-completion-schemas.sh regenerates it when this fails."""
    committed = yaml.safe_load((SCHEMA_DIR / f"tokkeeper.{face}.yaml").read_text(encoding="utf-8"))
    assert committed == json_schemas()[face]
