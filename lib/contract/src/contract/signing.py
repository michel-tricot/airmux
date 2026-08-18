from __future__ import annotations

import base64
import json
from typing import Annotated

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BeforeValidator, PlainSerializer

from contract.bundle import BundleV1, SignedBundle


def private_key_to_b64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(raw).decode("ascii")


def private_key_from_b64(b64: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(b64))


def public_key_to_b64(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def public_key_from_b64(b64: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(b64))


def _private_key_before(v: object) -> object:
    return private_key_from_b64(v) if isinstance(v, str) else v


def _public_key_before(v: object) -> object:
    return public_key_from_b64(v) if isinstance(v, str) else v


Ed25519PrivateKeyB64 = Annotated[Ed25519PrivateKey, BeforeValidator(_private_key_before), PlainSerializer(private_key_to_b64, return_type=str)]
"""A config/model field that is base64 on the wire and a parsed key object in code; malformed keys fail at validation.

Models using it need arbitrary_types_allowed. Serializing emits the raw private key, so dump such
models deliberately.
"""

Ed25519PublicKeyB64 = Annotated[Ed25519PublicKey, BeforeValidator(_public_key_before), PlainSerializer(public_key_to_b64, return_type=str)]


def canonical_json(bundle: BundleV1) -> str:
    """Serialize a bundle once for storage, transport, and exact-byte signing."""
    return json.dumps(bundle.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_bundle(bundle: BundleV1, private_key: Ed25519PrivateKey, signing_key_id: str) -> SignedBundle:
    payload = canonical_json(bundle)
    signature = base64.b64encode(private_key.sign(payload.encode("utf-8"))).decode("ascii")
    return SignedBundle(payload=payload, signature=signature, signing_key_id=signing_key_id)


def verify_bundle(signed: SignedBundle, public_key: Ed25519PublicKey) -> BundleV1:
    public_key.verify(base64.b64decode(signed.signature), signed.payload.encode("utf-8"))
    return BundleV1.model_validate_json(signed.payload)
