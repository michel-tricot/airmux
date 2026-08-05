from __future__ import annotations

from typing import TYPE_CHECKING

from contract import verify_inference_token

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from contract import BundleV1, KeyEntry


def index_keys(bundle: BundleV1) -> dict[str, KeyEntry]:
    return {k.key_id: k for k in bundle.keys}


def authenticate(bearer: str, public_key: Ed25519PublicKey, index: dict[str, KeyEntry], revocations: frozenset[str]) -> KeyEntry | None:
    claims = verify_inference_token(bearer, public_key)
    if claims is None:
        return None
    key = index.get(claims.key_id)
    if key is None or key.disabled or key.org_id != claims.org_id or key.key_id in revocations:
        return None
    return key
