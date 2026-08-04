from __future__ import annotations

from typing import TYPE_CHECKING

import jwt
from pydantic import BaseModel, ConfigDict, ValidationError

if TYPE_CHECKING:
    from datetime import datetime

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class TokenClaims(BaseModel):
    """The identity a caller token asserts. Authorization lives in the bundle, not here.

    The token proves which key is calling; what that key may do right now
    (allowed_models, disabled, revocation) is always read from the current
    bundle, so policy changes and revocations take effect within one poll
    interval regardless of what the token says.
    """

    model_config = ConfigDict(frozen=True)

    key_id: str
    org_id: str


def mint_api_token(key_id: str, org_id: str, private_key: Ed25519PrivateKey, issued_at: datetime) -> str:
    """Mint a caller API token: an EdDSA-signed JWT, stateless to verify."""
    return jwt.encode({"sub": key_id, "org": org_id, "iat": int(issued_at.timestamp())}, private_key, algorithm="EdDSA")


def verify_api_token(token: str, public_key: Ed25519PublicKey) -> TokenClaims | None:
    """Verify signature and shape; returns None on any failure. Zero I/O."""
    try:
        payload = jwt.decode(token, public_key, algorithms=["EdDSA"])
        return TokenClaims(key_id=payload["sub"], org_id=payload["org"])
    except (jwt.InvalidTokenError, KeyError, ValidationError):
        return None
