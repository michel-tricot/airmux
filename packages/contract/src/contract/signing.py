from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

from contract.bundle import BundleV1, SignedBundle

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def canonical_json(bundle: BundleV1) -> str:
    """The exact bytes signatures are computed over: sorted keys, no whitespace, UTF-8.

    The payload travels as a plain JSON object, so verification re-canonicalizes
    it with this same function. That only works while serialization is
    deterministic for every field type in the bundle; both planes must run the
    same contract version.
    """
    return json.dumps(bundle.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_bundle(bundle: BundleV1, private_key: Ed25519PrivateKey, signing_key_id: str) -> SignedBundle:
    signature = base64.b64encode(private_key.sign(canonical_json(bundle).encode("utf-8"))).decode("ascii")
    return SignedBundle(payload=bundle, signature=signature, signing_key_id=signing_key_id)


def verify_bundle(signed: SignedBundle, public_key: Ed25519PublicKey) -> BundleV1:
    public_key.verify(base64.b64decode(signed.signature), canonical_json(signed.payload).encode("utf-8"))
    return signed.payload
