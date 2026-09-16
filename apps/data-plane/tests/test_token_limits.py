from __future__ import annotations

import json

import pytest
from conftest import MODEL, PROVIDER, make_bundle

from contract import Catalog, Secret
from data_plane.bundle.holder import BundleSnapshot
from data_plane.canonical import CanonicalRequest
from data_plane.egress import REGISTRY
from data_plane.ingress import REGISTRY as INGRESS

BODY = {"model": MODEL.model_id, "messages": [{"role": "user", "content": "hi"}]}


@pytest.mark.parametrize("dialect", sorted(INGRESS))
def test_native_output_token_limits_enter_canonical_before_policy(dialect):
    body = (
        {"model": MODEL.model_id, "input": "hi", "max_output_tokens": 8}
        if dialect == "openai_responses"
        else {**BODY, "max_completion_tokens" if dialect == "openai_chat_completions" else "max_tokens": 8}
    )
    request, _ = INGRESS[dialect].parse(body)
    assert request.max_output_tokens == 8
    assert not request.extra


def test_openai_chat_rejects_both_output_limit_spellings():
    with pytest.raises(ValueError, match="not both"):
        INGRESS["openai_chat_completions"].parse({**BODY, "max_tokens": 8, "max_completion_tokens": 9})


@pytest.mark.parametrize(
    ("dialect", "body"),
    [
        ("openai_chat_completions", {**BODY, "max_output_tokens": 8}),
        ("openai_responses", {"model": MODEL.model_id, "input": "hi", "max_tokens": 8}),
        ("anthropic", {**BODY, "max_tokens": 8, "max_output_tokens": 8}),
    ],
)
def test_each_ingress_rejects_other_protocols_output_limit_spellings(dialect, body):
    with pytest.raises(ValueError, match=r"max.*tokens"):
        INGRESS[dialect].parse(body)


@pytest.mark.parametrize("limit", [pytest.param(None, id="null"), pytest.param("missing", id="missing")])
def test_anthropic_requires_its_output_limit(limit):
    body = BODY if limit == "missing" else {**BODY, "max_tokens": limit}
    with pytest.raises(ValueError, match="max_tokens is required"):
        INGRESS["anthropic"].parse(body)


@pytest.mark.parametrize("limit", [0, -1])
@pytest.mark.parametrize("dialect", sorted(INGRESS))
def test_output_limits_reject_non_positive_values(dialect, limit):
    body = (
        {"model": MODEL.model_id, "input": "hi", "max_output_tokens": limit}
        if dialect == "openai_responses"
        else {**BODY, "max_completion_tokens" if dialect == "openai_chat_completions" else "max_tokens": limit}
    )

    with pytest.raises(ValueError, match="greater than or equal to 1"):
        INGRESS[dialect].parse(body)


def test_all_provider_parameter_aliases_come_from_the_bundle() -> None:
    provider = PROVIDER.model_copy(update={"param_aliases": {"max_output_tokens": "provider_output_limit", "temperature": "provider_temperature"}})
    bundle = make_bundle(catalog=Catalog(providers=[provider], models=[MODEL]))
    snapshot = BundleSnapshot.from_bundle(bundle)
    assert snapshot.provider_param_aliases == frozenset({"provider_output_limit", "provider_temperature"})
    assert CanonicalRequest.model_validate({**BODY, "max_new_tokens": 9}).extra == {"max_new_tokens": 9}


@pytest.mark.parametrize("kind", sorted(REGISTRY))
def test_provider_receives_the_checked_limit_and_unrelated_passthrough(kind):
    provider = PROVIDER.model_copy(update={"kind": kind})
    adapter = REGISTRY[kind](provider, Secret("sk-test"))
    request = CanonicalRequest.model_validate({**BODY, "max_output_tokens": 1, "top_k": 5})
    sent = json.loads(adapter.transform_request(request, MODEL).body)
    assert sent["max_output_tokens" if kind == "openai_responses" else "max_tokens"] == 1
    assert sent["top_k"] == 5
