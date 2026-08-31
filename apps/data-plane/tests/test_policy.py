from __future__ import annotations

import pytest
from conftest import MODEL, PROVIDER, make_bundle, make_credential, make_key

from contract import Catalog, uuid7
from data_plane.bundle import BundleSnapshot
from data_plane.canonical import (
    CanonicalMessage,
    CanonicalRequest,
    DocumentPart,
    ImagePart,
    ReasoningConfig,
    ReasoningPart,
    ResponseFormat,
    ToolCallPart,
    ToolDef,
)
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


def test_model_without_provider_is_rejected_at_bundle_admission():
    bundle = make_bundle(catalog=Catalog(providers=[], models=[MODEL]), org=ORG_A)
    with pytest.raises(ValueError, match="unknown provider"):
        snap(bundle)


def test_request_capabilities_are_derived_from_every_canonical_feature():
    request = CanonicalRequest(
        model=MODEL.model_id,
        messages=[
            CanonicalMessage(role="user", content=[ImagePart(url="https://example.com/image.png"), DocumentPart(url="https://example.com/doc.pdf")]),
            CanonicalMessage(role="assistant", content=[ReasoningPart(text="think"), ToolCallPart(id="call-1", name="lookup", arguments="{}")]),
        ],
        stream=True,
        tools=[ToolDef(name="lookup")],
        reasoning=ReasoningConfig(effort="low"),
        response_format=ResponseFormat(type="json_object"),
    )

    decision = evaluate(request, KEY, snap(BUNDLE))

    assert isinstance(decision, Allow)


def test_request_is_denied_before_egress_when_the_model_lacks_a_required_capability():
    model = MODEL.model_copy(update={"capabilities": ["streaming"]})
    bundle = make_bundle(catalog=Catalog(providers=[PROVIDER], models=[model], credentials=[CREDENTIAL]), org=ORG_A)
    request = CanonicalRequest(
        model=model.model_id,
        messages=[{"role": "user", "content": "hi"}],
        tools=[ToolDef(name="lookup")],
    )

    assert evaluate(request, KEY, snap(bundle)) == Deny(reason="unsupported_feature: tools", status=400)
