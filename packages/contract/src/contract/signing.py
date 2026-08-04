from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

from contract.bundle import BundleV1, SignedBundle

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def canonical_json(bundle: BundleV1) -> str:
    return json.dumps(bundle.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_bundle(bundle: BundleV1, private_key: Ed25519PrivateKey, signing_key_id: str) -> SignedBundle:
    payload = canonical_json(bundle)
    signature = base64.b64encode(private_key.sign(payload.encode("utf-8"))).decode("ascii")
    return SignedBundle(payload=payload, signature=signature, signing_key_id=signing_key_id)


def verify_bundle(signed: SignedBundle, public_key: Ed25519PublicKey) -> BundleV1:
    public_key.verify(base64.b64decode(signed.signature), signed.payload.encode("utf-8"))
    return BundleV1.model_validate_json(signed.payload)
