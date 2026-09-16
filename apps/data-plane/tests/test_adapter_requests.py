from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from conftest import CTX, MODEL, PROVIDER
from corpus import CORPUS, request_of
from jsonschema import Draft202012Validator

from contract import Secret
from data_plane.canonical import (
    CanonicalDocumentPart,
    CanonicalJsonSchemaResponseFormat,
    CanonicalReasoningConfig,
    CanonicalReasoningPart,
    CanonicalRequest,
    CanonicalTextPart,
    CanonicalToolDef,
    CanonicalUserMessage,
)
from data_plane.egress import REGISTRY
from data_plane.egress.base import UpstreamResponseError

if TYPE_CHECKING:
    from jsonschema.protocols import Validator

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "taxonomy" / "schemas" / "completion"

# The reference vendor per wire family: its own extracted schema arbitrates what the adapter renders.
REFERENCE_SCHEMA = {
    "openai_compatible": "oai.openai.request.json",
    "openai_responses": "oai_responses.openai.request.json",
    "anthropic": "anthropic.anthropic.request.json",
}
ERROR_CASES = (
    ("openai_compatible", {"error": {"code": "rate_limit_exceeded", "message": "slow down"}}, "rate_limit_exceeded", "slow down"),
    ("openai_compatible", {"error": "File content is not supported"}, "429", "File content is not supported"),
    ("openai_compatible", {"code": "invalid-argument", "error": "Model does not support stop"}, "invalid-argument", "Model does not support stop"),
    (
        "openai_compatible",
        {
            "object": "error",
            "message": "reasoning_effort is not enabled for this model",
            "type": "invalid_request_invalid_args",
            "code": "3051",
        },
        "3051",
        "reasoning_effort is not enabled for this model",
    ),
    (
        "openai_compatible",
        {"object": "error", "message": "25 validation errors", "code": 400},
        "400",
        "25 validation errors",
    ),
    (
        "openai_compatible",
        {"detail": [{"type": "string_type", "loc": ["body", "messages", 0, "content"], "msg": "Input should be a valid string"}]},
        "429",
        '{"detail":[{"type":"string_type","loc":["body","messages",0,"content"],"msg":"Input should be a valid string"}]}',
    ),
    ("openai_compatible", "temporary provider failure", "429", "temporary provider failure"),
    ("openai_responses", {"error": {"code": "rate_limit_exceeded", "message": "slow down"}}, "rate_limit_exceeded", "slow down"),
    ("anthropic", {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}, "rate_limit_error", "slow down"),
)
ASSISTANT_PART_TYPES = {kind: set() for kind in REGISTRY}


def _assistant_part_types(body: object) -> set[str]:
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        content = node.get("content")
        if node.get("role") == "assistant" and isinstance(content, list):
            for part in content:
                kind = part.get("type") if isinstance(part, dict) else None
                if isinstance(kind, str):
                    found.add(kind)
        for value in node.values():
            walk(value)

    walk(body)
    return found


def _validator(kind: str) -> Validator:
    schema = json.loads((SCHEMA_DIR / REFERENCE_SCHEMA[kind]).read_text(encoding="utf-8"))
    if kind == "openai_responses":
        schema = _openapi_unions(schema)
    return Draft202012Validator(schema)


def _openapi_unions(value):
    """OpenAI's Responses spec has overlapping discriminator branches, which are valid
    OpenAPI but fail JSON Schema's exactly-one interpretation of oneOf."""
    if isinstance(value, list):
        return [_openapi_unions(item) for item in value]
    if not isinstance(value, dict):
        return value
    mapped = {key: _openapi_unions(item) for key, item in value.items()}
    if "oneOf" in mapped:
        mapped["anyOf"] = mapped.pop("oneOf")
    return mapped


def _adapter(kind: str):
    provider = PROVIDER.model_copy(update={"kind": kind})
    return REGISTRY[kind](provider, Secret("sk-test")), MODEL


@pytest.mark.parametrize("kind", sorted(REGISTRY))
@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c.name)
def test_every_corpus_case_renders_a_schema_valid_upstream_request(kind, case):
    """The provider's own published schema arbitrates, not a transcription of it."""
    adapter, model = _adapter(kind)
    if kind == "openai_responses" and case.stop is not None:
        with pytest.raises(ValueError, match="not representable by Responses"):
            adapter.transform_request(request_of(case), model)
        return
    upstream = adapter.transform_request(request_of(case), model)
    body = json.loads(upstream.body)
    errors = [f"{list(e.path)}: {e.message}" for e in _validator(kind).iter_errors(body)]
    assert not errors, "\n".join(errors)


@pytest.mark.parametrize("kind", sorted(REGISTRY))
def test_a_replayed_assistant_turn_is_rendered_as_something_the_model_said(kind):
    case = next(c for c in CORPUS if c.name == "multi_turn_text")
    adapter, model = _adapter(kind)
    upstream = adapter.transform_request(request_of(case), model)
    assert _assistant_part_types(json.loads(upstream.body)) == ASSISTANT_PART_TYPES[kind]
    assert "Paris" in upstream.body.decode()


@pytest.mark.parametrize("kind", sorted(REGISTRY))
def test_the_upstream_request_names_the_upstream_model_and_spends_the_injected_credential(kind):
    adapter, model = _adapter(kind)
    upstream = adapter.transform_request(request_of(CORPUS[0]), model)
    assert json.loads(upstream.body)["model"] == model.upstream_model
    assert "sk-test" in upstream.headers.get("authorization", "") or "sk-test" in upstream.headers.get("x-api-key", "")


@pytest.mark.parametrize(("kind", "body", "code", "message"), ERROR_CASES)
def test_provider_http_errors_become_canonical(kind, body, code, message):
    adapter, _ = _adapter(kind)
    error = adapter.map_error(UpstreamResponseError(429, json.dumps(body).encode()))
    assert (error.status, error.code, error.message) == (429, code, message)


def test_openai_compatible_validation_error_uses_the_http_status_as_its_code():
    adapter, _ = _adapter("openai_compatible")
    body = {"detail": [{"type": "extra_forbidden", "loc": ["body", "seed"], "msg": "Extra inputs are not permitted"}]}

    error = adapter.map_error(UpstreamResponseError(422, json.dumps(body).encode()))

    assert error.code == "422"
    assert "seed" in error.message


def test_openai_compatible_preserves_mistral_nested_validation_details():
    adapter, _ = _adapter("openai_compatible")
    body = {
        "object": "error",
        "message": {"detail": [{"type": "extra_forbidden", "loc": ["body", "seed"], "msg": "Extra inputs are not permitted"}]},
        "type": "invalid_request_error",
        "code": None,
        "raw_status_code": 422,
    }

    error = adapter.map_error(UpstreamResponseError(422, json.dumps(body).encode()))

    assert error.code == "422"
    assert "seed" in error.message


def test_openai_compatible_accepts_null_prompt_token_details():
    adapter, _ = _adapter("openai_compatible")
    response = {
        "id": "response-1",
        "choices": [{"message": {"content": "ok", "reasoning_content": "brief"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 17, "completion_tokens": 4, "prompt_tokens_details": None},
    }

    final = adapter.transform_response(json.dumps(response).encode(), CTX)

    assert final.usage.input_tokens == 17
    assert final.usage.cache_read_tokens == 0


def test_openai_compatible_preserves_reasoning_spelled_without_content():
    adapter, _ = _adapter("openai_compatible")
    response = {
        "id": "response-1",
        "choices": [{"message": {"content": "42", "reasoning": "20 + 22"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 17, "completion_tokens": 4},
    }

    final = adapter.transform_response(json.dumps(response).encode(), CTX)

    assert final.content == [CanonicalReasoningPart(text="20 + 22"), CanonicalTextPart(text="42")]


def test_openai_compatible_preserves_mistral_content_blocks():
    adapter, _ = _adapter("openai_compatible")
    response = {
        "id": "response-1",
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": [{"type": "text", "text": "20 + 22"}], "closed": True},
                        {"type": "text", "text": "42"},
                    ]
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 17, "completion_tokens": 4},
    }

    final = adapter.transform_response(json.dumps(response).encode(), CTX)

    assert final.content == [CanonicalReasoningPart(text="20 + 22"), CanonicalTextPart(text="42")]


@pytest.mark.parametrize("kind", sorted(REGISTRY))
def test_surviving_extras_merge_after_the_typed_body(kind):
    """The reconcile step upstream of the adapter decides what survives; the adapter renders
    whatever extras remain, after the typed fields."""
    adapter, model = _adapter(kind)
    body = json.loads(request_of(CORPUS[0]).model_dump_json())
    request = CanonicalRequest.model_validate({**body, "frequency_penalty": 0.5})
    upstream = adapter.transform_request(request, model)
    assert json.loads(upstream.body)["frequency_penalty"] == 0.5


def test_responses_applies_provider_aliases_after_the_explicit_field_mapping():
    provider = PROVIDER.model_copy(update={"kind": "openai_responses", "param_aliases": {"max_output_tokens": "max_tokens"}})
    adapter = REGISTRY["openai_responses"](provider, Secret("sk-test"))
    request = request_of(CORPUS[0], max_output_tokens=64)

    sent = json.loads(adapter.transform_request(request, MODEL).body)

    assert sent["max_tokens"] == 64
    assert "max_output_tokens" not in sent


def test_the_provider_spelling_wins_and_an_extra_never_overrides_it():
    adapter, model = _adapter("openai_compatible")
    provider = PROVIDER.model_copy(update={"param_aliases": {"max_output_tokens": "max_completion_tokens"}})
    adapter.provider = provider
    body = json.loads(request_of(CORPUS[0]).model_dump_json())
    request = CanonicalRequest.model_validate({**body, "max_output_tokens": 64, "max_completion_tokens": 999})
    sent = json.loads(adapter.transform_request(request, model).body)
    assert sent["max_completion_tokens"] == 64  # the canonical value, in the provider's spelling
    assert "max_tokens" not in sent


def test_openai_inline_document_without_a_name_gets_a_pdf_filename():
    adapter, model = _adapter("openai_compatible")
    request = CanonicalRequest(
        model=model.model_id,
        messages=[CanonicalUserMessage(content=[CanonicalDocumentPart(media_type="application/pdf", data="JVBERi0=")])],
    )

    sent = json.loads(adapter.transform_request(request, model).body)

    assert sent["messages"][0]["content"][0] == {
        "type": "file",
        "file": {"filename": "document.pdf", "file_data": "data:application/pdf;base64,JVBERi0="},
    }


def test_responses_inline_document_without_a_name_gets_a_pdf_filename():
    adapter, model = _adapter("openai_responses")
    request = CanonicalRequest(
        model=model.model_id,
        messages=[CanonicalUserMessage(content=[CanonicalDocumentPart(media_type="application/pdf", data="JVBERi0=")])],
    )

    sent = json.loads(adapter.transform_request(request, model).body)

    assert sent["input"][0]["content"][0] == {
        "type": "input_file",
        "filename": "document.pdf",
        "file_data": "data:application/pdf;base64,JVBERi0=",
    }


def test_a_failed_buffered_responses_result_is_not_rendered_as_success():
    adapter, _ = _adapter("openai_responses")
    response = {"id": "response-1", "status": "failed", "output": [], "error": {"code": "server_error", "message": "failed"}}

    with pytest.raises(ValueError, match="invalid upstream response"):
        adapter.transform_response(json.dumps(response).encode(), CTX)


def test_openai_json_schema_without_a_name_gets_a_stable_name():
    adapter, model = _adapter("openai_compatible")
    request = request_of(
        CORPUS[0],
        response_format=CanonicalJsonSchemaResponseFormat(json_schema={"schema": {"type": "object"}}),
    )

    sent = json.loads(adapter.transform_request(request, model).body)

    assert sent["response_format"]["json_schema"] == {"name": "response", "schema": {"type": "object"}}


def test_responses_json_schema_without_a_name_gets_a_stable_name():
    adapter, model = _adapter("openai_responses")
    request = request_of(
        CORPUS[0],
        response_format=CanonicalJsonSchemaResponseFormat(json_schema={"schema": {"type": "object"}}),
    )

    sent = json.loads(adapter.transform_request(request, model).body)

    assert sent["text"]["format"] == {"type": "json_schema", "name": "response", "schema": {"type": "object"}}


def test_openai_chat_maps_supported_reasoning_and_tool_options():
    adapter, model = _adapter("openai_compatible")
    request = request_of(
        CORPUS[0],
        reasoning=CanonicalReasoningConfig(effort="low"),
        parallel_tool_calls=True,
        tools=[CanonicalToolDef(name="answer", parameters={"type": "object"}, strict=True)],
    )

    sent = json.loads(adapter.transform_request(request, model).body)

    assert sent["reasoning_effort"] == "low"
    assert sent["parallel_tool_calls"] is True
    assert sent["tools"][0]["function"]["strict"] is True


def test_anthropic_maps_reasoning_structured_output_and_tool_options():
    adapter, model = _adapter("anthropic")
    request = request_of(
        CORPUS[0],
        reasoning=CanonicalReasoningConfig(effort="low", summary="auto"),
        parallel_tool_calls=True,
        tools=[CanonicalToolDef(name="answer", parameters={"type": "object"}, strict=True)],
        tool_choice="required",
        response_format=CanonicalJsonSchemaResponseFormat(
            json_schema={"name": "answer", "schema": {"type": "object", "properties": {"answer": {"type": "integer"}}}},
        ),
    )

    sent = json.loads(adapter.transform_request(request, model).body)

    assert sent["thinking"] == {"type": "adaptive"}
    assert sent["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": {"type": "object", "properties": {"answer": {"type": "integer"}}}},
    }
    assert sent["tool_choice"] == {"type": "any", "disable_parallel_tool_use": False}
    assert sent["tools"][0]["strict"] is True
