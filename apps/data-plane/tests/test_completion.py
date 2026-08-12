from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from corpus import CORPUS, request_of
from pydantic import ValidationError

from data_plane.canonical import (
    CanonicalChunk,
    CanonicalMessage,
    CanonicalRequest,
    CanonicalResponse,
    ImagePart,
    ReasoningDelta,
    ReasoningPart,
    TextDelta,
    TextPart,
    ToolCallDelta,
    ToolCallPart,
    ToolResultPart,
    Usage,
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
    assert reached == {"text", "image", "reasoning", "tool_call", "tool_result"}


@pytest.mark.parametrize(
    ("role", "part"),
    [
        ("system", ImagePart(url="https://example.com/cat.png")),
        ("system", ToolCallPart(id="c1", name="f", arguments="{}")),
        ("user", ToolCallPart(id="c1", name="f", arguments="{}")),
        ("user", ReasoningPart(text="hm")),
        ("assistant", ToolResultPart(call_id="c1", content=[TextPart(text="out")])),
        ("assistant", ImagePart(url="https://example.com/cat.png")),
    ],
)
def test_a_part_outside_its_role_is_rejected(role, part):
    with pytest.raises(ValidationError, match="cannot carry"):
        CanonicalMessage(role=role, content=[part])


def test_an_image_needs_exactly_one_source():
    with pytest.raises(ValidationError, match="exactly one"):
        ImagePart(url="https://example.com/cat.png", data="iVBORw0KGgo=", media_type="image/png")
    with pytest.raises(ValidationError, match="exactly one"):
        ImagePart(media_type="image/png")
    with pytest.raises(ValidationError, match="media_type"):
        ImagePart(data="iVBORw0KGgo=")


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


def test_an_unknown_field_is_rejected_not_dropped():
    """The definition is closed: silently dropping a field the caller set is how a gateway loses trust."""
    body = {"model": "m", "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}], "frequency_penalty": 0.5}
    with pytest.raises(ValidationError, match="frequency_penalty"):
        CanonicalRequest.model_validate(body)


def test_the_definition_is_frozen():
    request = request_of(CORPUS[0])
    with pytest.raises(ValidationError):
        request.model = "other"


def test_a_stream_of_typed_deltas_reassembles_the_response():
    """The stream face and the response face describe the same conversation: folding one yields the other."""
    chunks = [
        CanonicalChunk(id="r1", delta=ReasoningDelta(text="think ")),
        CanonicalChunk(id="r1", delta=ReasoningDelta(text="hard", signature="sig_1")),
        CanonicalChunk(id="r1", delta=TextDelta(text="hé")),
        CanonicalChunk(id="r1", delta=TextDelta(text="llo")),
        CanonicalChunk(id="r1", delta=ToolCallDelta(index=0, id="call_1", name="get_weather", arguments='{"ci')),
        CanonicalChunk(id="r1", delta=ToolCallDelta(index=0, arguments='ty":"Paris"}')),
        CanonicalChunk(id="r1", finish_reason="tool_calls", usage=Usage(input_tokens=5, output_tokens=7)),
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
    assert closing.usage == Usage(input_tokens=5, output_tokens=7)


@pytest.mark.parametrize("face", ["request", "response", "stream"])
def test_the_committed_schema_matches_the_definition(face):
    """taxonomy/schemas/completion is the published word on what the gateway accepts and emits;
    scripts/export-completion-schemas.sh regenerates it when this fails."""
    committed = yaml.safe_load((SCHEMA_DIR / f"airllm.{face}.yaml").read_text(encoding="utf-8"))
    assert committed == json_schemas()[face]
