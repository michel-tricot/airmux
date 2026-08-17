from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from conftest import MODEL, PROVIDER
from corpus import CORPUS, request_of
from jsonschema import Draft202012Validator

from contract import Secret
from data_plane.canonical import CanonicalRequest
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
ERROR_BODY = {
    "openai_compatible": ({"error": {"code": "rate_limit_exceeded", "message": "slow down"}}, "rate_limit_exceeded"),
    "openai_responses": ({"error": {"code": "rate_limit_exceeded", "message": "slow down"}}, "rate_limit_exceeded"),
    "anthropic": ({"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}, "rate_limit_error"),
}


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
def test_the_upstream_request_names_the_upstream_model_and_spends_the_injected_credential(kind):
    adapter, model = _adapter(kind)
    upstream = adapter.transform_request(request_of(CORPUS[0]), model)
    assert json.loads(upstream.body)["model"] == model.upstream_model
    assert "sk-test" in upstream.headers.get("authorization", "") or "sk-test" in upstream.headers.get("x-api-key", "")


@pytest.mark.parametrize("kind", sorted(REGISTRY))
def test_provider_http_errors_become_canonical(kind):
    adapter, _ = _adapter(kind)
    body, code = ERROR_BODY[kind]
    error = adapter.map_error(UpstreamResponseError(429, json.dumps(body).encode()))
    assert (error.status, error.code, error.message) == (429, code, "slow down")


@pytest.mark.parametrize("kind", sorted(REGISTRY))
def test_surviving_extras_merge_after_the_typed_body(kind):
    """The reconcile step upstream of the adapter decides what survives; the adapter renders
    whatever extras remain, after the typed fields."""
    adapter, model = _adapter(kind)
    body = json.loads(request_of(CORPUS[0]).model_dump_json())
    request = CanonicalRequest.model_validate({**body, "frequency_penalty": 0.5})
    if kind == "openai_responses":
        with pytest.raises(ValueError, match="not representable by Responses"):
            adapter.transform_request(request, model)
        return
    upstream = adapter.transform_request(request, model)
    assert json.loads(upstream.body)["frequency_penalty"] == 0.5


def test_the_provider_spelling_wins_and_an_extra_never_overrides_it():
    adapter, model = _adapter("openai_compatible")
    provider = PROVIDER.model_copy(update={"param_aliases": {"max_tokens": "max_completion_tokens"}})
    adapter.provider = provider
    body = json.loads(request_of(CORPUS[0]).model_dump_json())
    request = CanonicalRequest.model_validate({**body, "max_tokens": 64, "max_completion_tokens": 999})
    sent = json.loads(adapter.transform_request(request, model).body)
    assert sent["max_completion_tokens"] == 64  # the canonical value, in the provider's spelling
    assert "max_tokens" not in sent
