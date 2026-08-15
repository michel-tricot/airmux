from __future__ import annotations

from conftest import MODEL, PROVIDER, make_bundle, make_credential, make_key

from contract import Catalog, uuid7
from data_plane.bundle import BundleSnapshot
from data_plane.canonical import CanonicalRequest
from data_plane.policy import Allow, Deny, evaluate

ORG_A = uuid7()

CREDENTIAL = make_credential(org=ORG_A)
BUNDLE = make_bundle(catalog=Catalog(providers=[PROVIDER], models=[MODEL], credentials=[CREDENTIAL]), org=ORG_A)

KEY = make_key("k1", org=ORG_A)[1]


def snap(bundle):
    return BundleSnapshot.from_bundle(bundle)


def make_request(model="gpt-test"):
    return CanonicalRequest(model=model, messages=[{"role": "user", "content": "hi"}])


def test_snapshot_indexes_catalog():
    snapshot = snap(BUNDLE)
    assert snapshot.model_index == {"gpt-test": MODEL}
    assert snapshot.provider_index == {"p1": PROVIDER}


def test_catalog_model_allowed():
    decision = evaluate(make_request(), KEY, snap(BUNDLE))
    assert isinstance(decision, Allow)
    assert decision.model.upstream_model == "gpt-real"
    assert decision.provider.provider_id == "p1"


def test_unknown_model_denied_404():
    decision = evaluate(make_request("nope"), KEY, snap(BUNDLE))
    assert decision == Deny(reason="unknown_model", status=404)


def test_model_without_provider_denied_502():
    bundle = make_bundle(catalog=Catalog(providers=[], models=[MODEL]), org=ORG_A)
    decision = evaluate(make_request(), KEY, snap(bundle))
    assert decision == Deny(reason="provider_not_configured", status=502)
