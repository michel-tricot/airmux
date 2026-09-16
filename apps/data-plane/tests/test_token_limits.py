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
    assert request.max_tokens == 8
    assert not request.extra


def test_all_provider_parameter_aliases_come_from_the_bundle() -> None:
    provider = PROVIDER.model_copy(update={"param_aliases": {"max_tokens": "provider_output_limit", "temperature": "provider_temperature"}})
    bundle = make_bundle(catalog=Catalog(providers=[provider], models=[MODEL]))
    snapshot = BundleSnapshot.from_bundle(bundle)
    assert snapshot.provider_param_aliases == frozenset({"provider_output_limit", "provider_temperature"})
    assert CanonicalRequest.model_validate({**BODY, "max_new_tokens": 9}).extra == {"max_new_tokens": 9}


@pytest.mark.parametrize("kind", sorted(REGISTRY))
def test_provider_receives_the_checked_limit_and_unrelated_passthrough(kind):
    provider = PROVIDER.model_copy(update={"kind": kind})
    adapter = REGISTRY[kind](provider, Secret("sk-test"))
    request = CanonicalRequest.model_validate({**BODY, "max_tokens": 1, "top_k": 5})
    sent = json.loads(adapter.transform_request(request, MODEL).body)
    assert sent["max_output_tokens" if kind == "openai_responses" else "max_tokens"] == 1
    assert sent["top_k"] == 5
