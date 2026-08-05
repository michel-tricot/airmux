from __future__ import annotations

from typing import TYPE_CHECKING, Any

import jwt
from pydantic import BaseModel, ConfigDict, ValidationError

if TYPE_CHECKING:
    from datetime import datetime

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

INFERENCE_TOKEN_PREFIX = "ab-inf-"  # noqa: S105 token prefix, not a secret

_INFERENCE_USE = "inference"


class InferenceClaims(BaseModel):
    """The identity an inference token asserts. Authorization lives in the bundle, not here.

    The token proves which key is calling; what that key may do right now
    (allowed_models, disabled, revocation) is always read from the current
    bundle, so policy changes and revocations take effect within one poll
    interval regardless of what the token says.
    """

    model_config = ConfigDict(frozen=True)

    key_id: str
    org_id: str


def _decode(token: str, prefix: str, use: str, public_key: Ed25519PublicKey) -> dict[str, Any] | None:
    if not token.startswith(prefix):
        return None
    try:
        payload = jwt.decode(token.removeprefix(prefix), public_key, algorithms=["EdDSA"])
    except jwt.InvalidTokenError:
        return None
    return payload if payload.get("use") == use else None


def mint_inference_token(key_id: str, org_id: str, private_key: Ed25519PrivateKey, issued_at: datetime) -> str:
    """Mint a data-plane caller token: a prefixed EdDSA-signed JWT, stateless to verify.

    The prefix keeps the token greppable and the hyphen before the JWT keeps
    the eyJ header detectable by generic VCS secret scanners.
    """
    payload = {"use": _INFERENCE_USE, "sub": key_id, "org": org_id, "iat": int(issued_at.timestamp())}
    return INFERENCE_TOKEN_PREFIX + jwt.encode(payload, private_key, algorithm="EdDSA")


def verify_inference_token(token: str, public_key: Ed25519PublicKey) -> InferenceClaims | None:
    """Verify prefix, signature, and shape; returns None on any failure. Zero I/O."""
    payload = _decode(token, INFERENCE_TOKEN_PREFIX, _INFERENCE_USE, public_key)
    if payload is None:
        return None
    try:
        return InferenceClaims(key_id=payload["sub"], org_id=payload["org"])
    except (KeyError, ValidationError):
        return None
