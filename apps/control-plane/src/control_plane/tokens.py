from __future__ import annotations

import secrets
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from contract import INFERENCE_TOKEN_PREFIX, token_hash
from control_plane.models import ApiKey, MgmtToken, OrgMembership, User

MANAGEMENT_TOKEN_PREFIX = "ab-mgmt-"  # noqa: S105 token prefix, not a secret


class ManagementClaims(BaseModel):
    """The scope a management key grants: one org, or the whole instance when org_id is None.

    Management keys are a control-plane concern only; the data plane never sees or
    verifies them. Claims are built from the key's database row, never parsed from
    the presented secret, and the claimed scope must be backed by the owning user's
    memberships at request time.
    """

    model_config = ConfigDict(frozen=True)

    token_id: str
    org_id: str | None = None
    user_id: str


def _new_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


async def mint_mgmt_key(org_id: str | None, user_id: str) -> tuple[str, str]:
    """Mint a management key and its backing row; returns (token_id, token).

    The plaintext exists only in the return value; the row stores its hash.
    Runs inside the caller's transaction.
    """
    token = _new_token(MANAGEMENT_TOKEN_PREFIX)
    token_id = f"mt-{uuid4().hex[:8]}"
    await MgmtToken(id=token_id, org_id=org_id, user_id=user_id, token_hash=token_hash(token), revoked=False).save()
    return token_id, token


async def mint_inference_key(org_id: str, user_id: str) -> tuple[str, str]:
    """Mint an inference API key row and its caller token; returns (key_id, token). Runs inside the caller's transaction."""
    token = _new_token(INFERENCE_TOKEN_PREFIX)
    key_id = f"k-{uuid4().hex[:8]}"
    await ApiKey(id=key_id, org_id=org_id, user_id=user_id, token_hash=token_hash(token), disabled=False).save()
    return key_id, token


async def verify_management_token(token: str) -> ManagementClaims | None:
    """Resolve a presented bearer to backed claims; returns None on any failure.

    One lookup by hash, then the backing checks: the row is not revoked and the owning
    user exists and holds the claimed scope (instance admin, or membership in the org).
    Lookup through the unique hash index is the timing-safe comparison.
    """
    if not token.startswith(MANAGEMENT_TOKEN_PREFIX):
        return None
    row = await MgmtToken.first(MgmtToken.token_hash == token_hash(token))
    if row is None or row.revoked:
        return None
    user = await User.get(row.user_id)
    if user is None:
        return None
    if not user.instance_admin and (row.org_id is None or await OrgMembership.get((row.user_id, row.org_id)) is None):
        return None
    return ManagementClaims(token_id=row.id, org_id=row.org_id, user_id=row.user_id)
