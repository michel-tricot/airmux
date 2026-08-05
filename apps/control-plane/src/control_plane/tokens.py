from __future__ import annotations

from typing import TYPE_CHECKING

import jwt
from pydantic import BaseModel, ConfigDict, ValidationError

if TYPE_CHECKING:
    from datetime import datetime

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

MANAGEMENT_TOKEN_PREFIX = "ab-mgmt-"  # noqa: S105 token prefix, not a secret

_MANAGEMENT_USE = "management"


class ManagementClaims(BaseModel):
    """The scope a management token asserts: one org, or the whole instance when org_id is None.

    Management tokens are a control-plane concern only; the data plane never sees or
    verifies them. token_id is the revocation handle: the control plane refuses tokens
    whose id it has marked revoked, so verification stays stateless but revocation does not.
    user_id binds the token to a user; the claimed scope must still be backed by that
    user's memberships at request time, checked against the database.
    """

    model_config = ConfigDict(frozen=True)

    token_id: str
    org_id: str | None = None
    user_id: str | None = None


def mint_management_token(org_id: str | None, private_key: Ed25519PrivateKey, issued_at: datetime, token_id: str, user_id: str | None = None) -> str:
    """Mint an admin token, scoped to one org or to the whole instance when org_id is None.

    Same shape as the contract's inference tokens: a prefixed EdDSA JWT whose hyphen
    keeps the eyJ header detectable by generic VCS secret scanners.
    """
    payload = {
        "use": _MANAGEMENT_USE,
        "jti": token_id,
        "iat": int(issued_at.timestamp()),
        **({"org": org_id} if org_id is not None else {}),
        **({"sub": user_id} if user_id is not None else {}),
    }
    return MANAGEMENT_TOKEN_PREFIX + jwt.encode(payload, private_key, algorithm="EdDSA")


def verify_management_token(token: str, public_key: Ed25519PublicKey) -> ManagementClaims | None:
    """Verify prefix, signature, and shape; returns None on any failure. Zero I/O."""
    if not token.startswith(MANAGEMENT_TOKEN_PREFIX):
        return None
    try:
        payload = jwt.decode(token.removeprefix(MANAGEMENT_TOKEN_PREFIX), public_key, algorithms=["EdDSA"])
    except jwt.InvalidTokenError:
        return None
    if payload.get("use") != _MANAGEMENT_USE:
        return None
    try:
        return ManagementClaims(token_id=payload["jti"], org_id=payload.get("org"), user_id=payload.get("sub"))
    except (KeyError, ValidationError):
        return None
