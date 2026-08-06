from __future__ import annotations

from conftest import MODEL, NOW, PROVIDER, make_bundle, make_key

from contract import Catalog
from data_plane.canonical import CanonicalRequest
from data_plane.policy import Allow, Deny, evaluate

BUNDLE = make_bundle(catalog=Catalog(providers=[PROVIDER], models=[MODEL]), org="org-a")

KEY = make_key("k1", org="org-a")[1]


def make_request(model="gpt-test"):
    return CanonicalRequest(model=model, messages=[{"role": "user", "content": "hi"}])


def test_catalog_model_allowed():
    decision = evaluate(make_request(), KEY, BUNDLE, NOW)
    assert isinstance(decision, Allow)
    assert decision.model.upstream_model == "gpt-real"
    assert decision.provider.provider_id == "p1"


def test_unknown_model_denied_404():
    decision = evaluate(make_request("nope"), KEY, BUNDLE, NOW)
    assert decision == Deny(reason="unknown_model", status=404)


def test_model_without_provider_denied_502():
    bundle = make_bundle(catalog=Catalog(providers=[], models=[MODEL]), org="org-a")
    decision = evaluate(make_request(), KEY, bundle, NOW)
    assert decision == Deny(reason="provider_not_configured", status=502)
