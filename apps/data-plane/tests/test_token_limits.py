from __future__ import annotations

import json

import pytest
from conftest import MODEL, PROVIDER
from pydantic import ValidationError

from contract import Secret
from data_plane.canonical import CanonicalRequest
from data_plane.egress import REGISTRY
from data_plane.ingress import REGISTRY as INGRESS

ALIASES = ("max_completion_tokens", "max_output_tokens", "max_new_tokens")
BODY = {"model": MODEL.model_id, "messages": [{"role": "user", "content": "hi"}]}


@pytest.mark.parametrize("alias", ALIASES)
@pytest.mark.parametrize("limit", [None, 1, 999])
def test_canonical_passthrough_rejects_output_token_aliases(alias, limit):
    with pytest.raises(ValidationError, match="output token limits must use max_tokens"):
        CanonicalRequest.model_validate({**BODY, "max_tokens": limit, alias: 999})


@pytest.mark.parametrize("dialect", sorted(INGRESS))
def test_native_output_token_limits_enter_canonical_before_policy(dialect):
    body = (
        {"model": MODEL.model_id, "input": "hi", "max_output_tokens": 8}
        if dialect == "openai_responses"
        else {**BODY, "max_completion_tokens" if dialect == "openai_native" else "max_tokens": 8}
    )
    request, _ = INGRESS[dialect].parse(body)
    assert request.max_tokens == 8
    assert not request.extra


@pytest.mark.parametrize("kind", sorted(REGISTRY))
@pytest.mark.parametrize("limit", [None, 1])
def test_configured_output_token_alias_cannot_enter_as_passthrough(kind, limit):
    provider = PROVIDER.model_copy(
        update={"kind": kind, "param_aliases": {"max_tokens": "custom_output_limit", "max_output_tokens": "custom_output_limit"}}
    )
    adapter = REGISTRY[kind](provider, Secret("sk-test"))
    request = CanonicalRequest.model_validate({**BODY, "max_tokens": limit, "custom_output_limit": 999})
    with pytest.raises(ValueError, match="output token limits must use max_tokens"):
        adapter.transform_request(request, MODEL)


@pytest.mark.parametrize("kind", sorted(REGISTRY))
def test_rendered_output_token_limit_cannot_be_replaced_by_another_typed_parameter(kind):
    limit_name = "max_output_tokens" if kind == "openai_responses" else "max_tokens"
    provider = PROVIDER.model_copy(update={"kind": kind, "param_aliases": {"temperature": limit_name}})
    adapter = REGISTRY[kind](provider, Secret("sk-test"))
    request = CanonicalRequest.model_validate({**BODY, "max_tokens": 1, "temperature": 999})
    with pytest.raises(ValueError, match="provider parameter aliases collide with output token limits"):
        adapter.transform_request(request, MODEL)


@pytest.mark.parametrize("kind", sorted(REGISTRY))
def test_provider_receives_the_checked_limit_and_unrelated_passthrough(kind):
    provider = PROVIDER.model_copy(update={"kind": kind})
    adapter = REGISTRY[kind](provider, Secret("sk-test"))
    request = CanonicalRequest.model_validate({**BODY, "max_tokens": 1, "top_k": 5})
    sent = json.loads(adapter.transform_request(request, MODEL).body)
    assert sent["max_output_tokens" if kind == "openai_responses" else "max_tokens"] == 1
    assert sent["top_k"] == 5
