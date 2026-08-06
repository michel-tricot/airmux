from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    private_key_to_b64,
    public_key_to_b64,
    sign_bundle,
    verify_bundle,
)


def make_bundle() -> BundleV1:
    now = datetime.now(tz=UTC)
    return BundleV1(
        bundle_id=uuid4(),
        org_id="org-test",
        issued_at=now,
        expires_at=now + timedelta(hours=24),
        keys=[],
        revocations=[],
        catalog=Catalog(providers=[], models=[]),
    )


def test_sign_and_verify_roundtrip():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle()
    signed = sign_bundle(bundle, private_key, "k1")
    assert verify_bundle(signed, private_key.public_key()) == bundle


def test_tampered_payload_rejected():
    private_key = Ed25519PrivateKey.generate()
    signed = sign_bundle(make_bundle(), private_key, "k1")
    tampered = signed.model_copy(update={"payload": signed.payload.model_copy(update={"org_id": "org-evil"})})
    with pytest.raises(InvalidSignature):
        verify_bundle(tampered, private_key.public_key())


def test_signature_survives_disk_roundtrip():
    private_key = Ed25519PrivateKey.generate()
    signed = sign_bundle(make_bundle(), private_key, "k1")
    reloaded = type(signed).model_validate_json(signed.model_dump_json(indent=2))
    assert verify_bundle(reloaded, private_key.public_key()) == signed.payload


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
