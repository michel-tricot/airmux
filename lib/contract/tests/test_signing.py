from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, ConfigDict

from contract import (
    BundleV1,
    Catalog,
    Ed25519PrivateKeyB64,
    Ed25519PublicKeyB64,
    SignedBundle,
    canonical_json,
    private_key_to_b64,
    public_key_to_b64,
    sign_bundle,
    uuid7,
    verify_bundle,
)


def make_bundle() -> BundleV1:
    now = datetime.now(tz=UTC)
    return BundleV1(
        bundle_id=uuid4(),
        org_id=uuid7(),
        issued_at=now,
        keys=[],
        catalog=Catalog(providers=[], models=[]),
    )


def test_sign_and_verify_roundtrip():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle()
    signed = sign_bundle(bundle, private_key, "k1")
    assert verify_bundle(signed, private_key.public_key()) == bundle


def test_signed_bundle_carries_the_exact_serialized_payload():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle()

    signed = sign_bundle(bundle, private_key, "k1")

    assert signed.payload == canonical_json(bundle)


def test_tampered_payload_rejected():
    private_key = Ed25519PrivateKey.generate()
    signed = sign_bundle(make_bundle(), private_key, "k1")
    tampered = signed.model_copy(update={"payload": f"{signed.payload} "})
    with pytest.raises(InvalidSignature):
        verify_bundle(tampered, private_key.public_key())


def test_signature_survives_disk_roundtrip():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle()
    signed = sign_bundle(bundle, private_key, "k1")
    reloaded = type(signed).model_validate_json(signed.model_dump_json(indent=2))
    assert verify_bundle(reloaded, private_key.public_key()) == bundle


def test_signature_is_checked_before_payload_parsing():
    private_key = Ed25519PrivateKey.generate()
    payload = "not json"
    signature = base64.b64encode(private_key.sign(b"different bytes")).decode("ascii")
    signed = SignedBundle(payload=payload, signature=signature, signing_key_id="k1")

    with pytest.raises(InvalidSignature):
        verify_bundle(signed, private_key.public_key())


def test_verified_payload_can_ignore_an_additive_field():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle()
    fields = {**bundle.model_dump(mode="json"), "future_field": {"enabled": True}}
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    signature = base64.b64encode(private_key.sign(payload.encode("utf-8"))).decode("ascii")
    signed = SignedBundle(payload=payload, signature=signature, signing_key_id="k1")

    assert verify_bundle(signed, private_key.public_key()) == bundle


def test_annotated_key_types_roundtrip_through_json():
    class Holder(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)

        private: Ed25519PrivateKeyB64
        public: Ed25519PublicKeyB64

    key = Ed25519PrivateKey.generate()
    holder = Holder(private=private_key_to_b64(key), public=key.public_key())
    restored = Holder.model_validate_json(holder.model_dump_json())
    assert private_key_to_b64(restored.private) == private_key_to_b64(key)
    assert public_key_to_b64(restored.public) == public_key_to_b64(key.public_key())
