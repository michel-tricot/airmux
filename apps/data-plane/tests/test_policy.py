from __future__ import annotations

from conftest import MODEL, NOW, PROVIDER, make_bundle

from contract import Catalog, KeyEntry
from data_plane.canonical import CanonicalRequest
from data_plane.policy import Allow, Deny, evaluate

BUNDLE = make_bundle(catalog=Catalog(providers=[PROVIDER], models=[MODEL]), org="org-a")


def make_request(model="gpt-test"):
    return CanonicalRequest(model=model, messages=[{"role": "user", "content": "hi"}])


def make_key(allowed_models):
    return KeyEntry(key_id="k1", org_id="org-a", allowed_models=allowed_models)


def test_wildcard_key_allowed():
    decision = evaluate(make_request(), make_key(["*"]), BUNDLE, NOW)
    assert isinstance(decision, Allow)
    assert decision.model.upstream_model == "gpt-real"
    assert decision.provider.provider_id == "p1"


def test_explicit_model_allowed():
    assert isinstance(evaluate(make_request(), make_key(["gpt-test"]), BUNDLE, NOW), Allow)


def test_unknown_model_denied_404():
    decision = evaluate(make_request("nope"), make_key(["*"]), BUNDLE, NOW)
    assert decision == Deny(reason="unknown_model", status=404)


def test_disallowed_model_denied_403():
    decision = evaluate(make_request(), make_key(["other-model"]), BUNDLE, NOW)
    assert decision == Deny(reason="model_not_allowed", status=403)
