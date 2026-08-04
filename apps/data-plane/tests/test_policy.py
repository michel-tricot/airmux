from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from contract import BundleV1, Catalog, KeyEntry, ModelEntry, ProviderEntry
from data_plane.canonical import CanonicalRequest
from data_plane.policy import Allow, Deny, evaluate

NOW = datetime.now(tz=UTC)

PROVIDER = ProviderEntry(provider_id="p1", kind="openai_compatible", base_url="https://api.openai.com/v1", credential_ref="env:OPENAI_API_KEY")
MODEL = ModelEntry(
    model_id="gpt-test",
    provider_id="p1",
    upstream_model="gpt-real",
    input_price_per_mtok=1.0,
    output_price_per_mtok=2.0,
    context_window=128000,
    capabilities=["streaming"],
)
BUNDLE = BundleV1(
    bundle_id=uuid4(),
    org_id="org-a",
    issued_at=NOW,
    expires_at=NOW + timedelta(hours=24),
    keys=[],
    revocations=[],
    catalog=Catalog(providers=[PROVIDER], models=[MODEL]),
)


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
