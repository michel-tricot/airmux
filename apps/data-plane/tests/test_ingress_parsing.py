from __future__ import annotations

import json

import pytest
from conftest import MODEL, PROVIDER, make_adapter
from ingress_cases import DOCUMENT_PARTS

from data_plane.canonical import (
    CanonicalDocumentPart,
    CanonicalJsonObjectResponseFormat,
    CanonicalJsonSchemaResponseFormat,
    CanonicalMessage,
    CanonicalTextPart,
)
from data_plane.formats.openai_responses import input_of, messages_of
from data_plane.ingress import REGISTRY
from data_plane.ingress.anthropic import AnthropicIngress
from data_plane.ingress.openai_native import OpenAINativeIngress
from data_plane.ingress.openai_responses import OpenAIResponsesIngress
from data_plane.profiles import compile_profile
from data_plane.reconcile import reconcile


@pytest.mark.parametrize("dialect", REGISTRY)
def test_document_content_survives_ingress(dialect):
    field = "input" if dialect == "openai_responses" else "messages"
    limit = {"max_tokens": 8} if dialect == "anthropic" else {}
    request, adjustments = REGISTRY[dialect].parse({"model": "gpt-test", field: [{"role": "user", "content": [DOCUMENT_PARTS[dialect]]}], **limit})
    assert request.messages[0].content == [CanonicalDocumentPart(media_type="application/pdf", data="JVBERi0=")]
    assert adjustments == []


TEXT_BODY = {"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]}


TOOL_ROLE_BODY = {
    "model": "gpt-test",
    "messages": [
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "w", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "18C"},
    ],
}


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


def test_openai_parse_translates_the_openai_shapes_and_keeps_the_rest():
    body = {
        **TOOL_ROLE_BODY,
        "tools": [{"type": "function", "function": {"name": "w", "description": "weather", "parameters": {"type": "object"}}}],
        "tool_choice": {"type": "function", "function": {"name": "w"}},
        "max_completion_tokens": 64,
        "frequency_penalty": 0.5,
        "stream_options": {"include_usage": True},
    }
    req, _ = OpenAINativeIngress().parse(body)
    roles = [(m.role, [p.type for p in m.content]) for m in req.messages]
    assert roles == [("user", ["text"]), ("assistant", ["tool_call"]), ("user", ["tool_result"])]
    assert req.tools is not None
    assert (req.tools[0].name, req.tools[0].description) == ("w", "weather")
    assert getattr(req.tool_choice, "name", None) == "w"
    assert req.max_output_tokens == 64
    assert req.extra == {"frequency_penalty": 0.5}  # stream_options consumed silently, the rest kept for the reconcile step


def test_openai_the_aligned_path_is_a_fixpoint():
    """OpenAI caller, OpenAI-family provider: parse, reconcile, render, parse again is the
    identity minus deliberate edits (the upstream model name). The waist provably costs the
    aligned path nothing, extras included."""
    body = {
        **TOOL_ROLE_BODY,
        "tools": [{"type": "function", "function": {"name": "w", "description": "weather", "parameters": {"type": "object"}}}],
        "temperature": 0.7,
        "frequency_penalty": 0.5,
    }
    ingress = OpenAINativeIngress()
    parsed, _ = ingress.parse(body)
    first, _ = reconcile(parsed, MODEL, compile_profile(PROVIDER))
    upstream = make_adapter().transform_request(first, MODEL)
    again, _ = ingress.parse(json.loads(upstream.body))
    assert again.model_dump(exclude={"model"}) == first.model_dump(exclude={"model"})


def test_openai_an_unknown_tool_choice_variant_is_never_silently_none():
    """A consumed slot with an unrecognized value is a translation loss the caller hears about:
    the typed tool_choice stays honestly unset and the parse reports the drop."""
    req, carried = OpenAINativeIngress().parse({**TEXT_BODY, "tool_choice": {"type": "allowed_tools", "tools": []}})
    assert req.tool_choice is None
    assert [(a.param, a.action) for a in carried] == [("tool_choice", "dropped")]


def test_openai_chat_reasoning_extension_preserves_summary_configuration():
    request, _ = OpenAINativeIngress().parse(
        {
            **TEXT_BODY,
            "reasoning_effort": "low",
            "reasoning": {"summary": "auto"},
        }
    )

    assert request.reasoning is not None
    assert request.reasoning.effort == "low"
    assert request.reasoning.summary == "auto"


def test_anthropic_parse_hoists_system_and_keeps_the_rest_as_extras():
    body = {
        "model": "gpt-test",
        "max_tokens": 64,
        "system": "You are terse.",
        "messages": [{"role": "user", "content": "hi"}],
        "stop_sequences": ["END"],
        "thinking": {"type": "enabled", "budget_tokens": 512},
        "metadata": {"user_id": "u1"},
    }
    req, adjustments = AnthropicIngress().parse(body)
    assert [m.role for m in req.messages] == ["system", "user"]
    assert req.max_output_tokens == 64
    assert req.stop == ["END"]
    assert req.reasoning is not None
    assert req.reasoning.type == "enabled"
    assert req.reasoning.budget_tokens == 512
    assert req.extra == {"metadata": {"user_id": "u1"}}
    assert adjustments == []


def test_anthropic_parse_strips_client_directive_blocks():
    body = {
        "model": "gpt-test",
        "max_tokens": 8,
        "system": [{"type": "text", "text": "x-anthropic-billing: abc"}, {"type": "text", "text": "Real prompt"}],
        "messages": [{"role": "user", "content": "hi"}],
    }
    req, _ = AnthropicIngress().parse(body)
    (system, _user) = req.messages
    assert [part.text for part in system.content if part.type == "text"] == ["Real prompt"]


def test_anthropic_parse_recovers_json_object_from_anthropic_generic_object_schema():
    request, _ = AnthropicIngress().parse(
        {
            "model": "gpt-test",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "answer with JSON"}],
            "output_config": {"format": {"type": "json_schema", "schema": {"type": "object"}}},
        }
    )

    assert request.response_format == CanonicalJsonObjectResponseFormat()


def test_anthropic_parse_keeps_a_constrained_anthropic_schema_as_json_schema():
    schema = {"type": "object", "properties": {"answer": {"type": "integer"}}}
    request, _ = AnthropicIngress().parse(
        {
            "model": "gpt-test",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "answer with JSON"}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
    )

    assert request.response_format == CanonicalJsonSchemaResponseFormat(json_schema={"name": "response", "strict": True, "schema": schema})


@pytest.mark.parametrize(("items", "expected"), [(i, e) for _, i, e in SPELLINGS], ids=[n for n, _, _ in SPELLINGS])
def test_responses_every_documented_input_spelling_survives_the_read(items, expected):
    assert _said(messages_of(items)) == expected


def test_responses_a_conversation_read_then_rewritten_keeps_every_turn():
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


def test_responses_json_schema_format_is_translated_into_canonical():
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


def test_responses_reasoning_configuration_is_translated_into_canonical():
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
