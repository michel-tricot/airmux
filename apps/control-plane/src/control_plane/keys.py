from __future__ import annotations

import secrets
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from contract import INFERENCE_TOKEN_PREFIX, token_hash
from control_plane.authz import ALL_SCOPES
from control_plane.models import InferenceKey, ManagementKey, OrgMembership, User

MANAGEMENT_KEY_PREFIX = "sk-mgmt-"


class ManagementClaims(BaseModel):
    """The scope a management key grants: one org, or the whole instance when org_id is None.

    Management keys are a control-plane concern only; the data plane never sees or
    verifies them. Claims are built from the key's database row, never parsed from
    the presented secret, and the claimed scope must be backed by the owning user's
    memberships at request time. scopes defaults to no authority so a construction
    site that forgets it fails closed; full authority (sessions, unrestricted keys)
    is always granted explicitly with ALL_SCOPES.
    """

    model_config = ConfigDict(frozen=True)

    token_id: UUID
    org_id: UUID | None = None
    user_id: UUID
    scopes: frozenset[str] = frozenset()


def _new_key(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


async def mint_management_key(org_id: UUID | None, user_id: UUID, *, label: str, scopes: list[str] | None = None) -> tuple[UUID, str]:
    """Mint a management key and its backing row; returns (key_id, token).

    The plaintext exists only in the return value; the row stores its hash.
    scopes=None mints an unrestricted key acting with the user's full authority.
    Every key carries a label so listings can say where it came from.
    Runs inside the caller's transaction.
    """
    token = _new_key(MANAGEMENT_KEY_PREFIX)
    key = await ManagementKey(org_id=org_id, user_id=user_id, token_hash=token_hash(token), revoked=False, scopes=scopes, label=label).save()
    return key.id, token


async def mint_inference_key(org_id: UUID, workspace_id: UUID, user_id: UUID, *, label: str) -> tuple[UUID, str]:
    """Mint an inference API key row and its caller token; returns (key_id, token). Runs inside the caller's transaction."""
    token = _new_key(INFERENCE_TOKEN_PREFIX)
    key = await InferenceKey(
        org_id=org_id, workspace_id=workspace_id, user_id=user_id, token_hash=token_hash(token), revoked=False, label=label
    ).save()
    return key.id, token


async def verify_management_key(token: str) -> ManagementClaims | None:
    """Resolve a presented bearer to backed claims; returns None on any failure.

    One lookup by hash, then the backing checks: the row is not revoked and the owning
    user exists and holds the claimed scope (instance admin, or membership in the org).
    Lookup through the unique hash index is the timing-safe comparison.
    """
    if not token.startswith(MANAGEMENT_KEY_PREFIX):
        return None
    key = await ManagementKey.first(ManagementKey.token_hash == token_hash(token))
    if key is None or key.revoked:
        return None
    user = await User.find_by_id(key.user_id)
    if user is None:
        return None
    if not user.instance_admin and (key.org_id is None or await OrgMembership.get((key.user_id, key.org_id)) is None):
        return None
    scopes = ALL_SCOPES if key.scopes is None else frozenset(key.scopes)
    return ManagementClaims(token_id=key.id, org_id=key.org_id, user_id=key.user_id, scopes=scopes)
