from __future__ import annotations

import secrets
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from contract import INFERENCE_TOKEN_PREFIX, token_hash
from control_plane.authz import ALL_SCOPES
from control_plane.models import InferenceKey, InstanceKey, ManagementKey, OrgMembership, User

MANAGEMENT_KEY_PREFIX = "sk-mgmt-"
INSTANCE_KEY_PREFIX = "sk-inst-"


class ManagementClaims(BaseModel):
    """The scope a credential grants: one org, or the whole instance when org_id is None.

    Instance scope comes from an instance key or an admin's session, never from a management
    key, which always names its org. Both key types are a control-plane concern only; the data
    plane never verifies them. Claims are built from the key's database row, never parsed from
    the presented secret, and the claimed scope must be backed at request time by the owning
    user's memberships or their instance_admin bit. scopes defaults to no authority so a
    construction site that forgets it fails closed; full authority (sessions, unrestricted keys)
    is always granted explicitly with ALL_SCOPES.
    """

    model_config = ConfigDict(frozen=True)

    token_id: UUID
    org_id: UUID | None = None
    user_id: UUID
    scopes: frozenset[str] = frozenset()


def _new_key(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


async def mint_management_key(org_id: UUID, user_id: UUID, *, label: str, scopes: list[str] | None = None) -> tuple[UUID, str]:
    """Mint an org-scoped management key and its backing row; returns (key_id, token).

    The plaintext exists only in the return value; the row stores its hash.
    scopes=None mints an unrestricted key acting with the user's full authority.
    Every key carries a label so listings can say where it came from.
    Runs inside the caller's transaction.
    """
    token = _new_key(MANAGEMENT_KEY_PREFIX)
    key = await ManagementKey(org_id=org_id, user_id=user_id, token_hash=token_hash(token), revoked=False, scopes=scopes, label=label).save()
    return key.id, token


async def mint_instance_key(user_id: UUID, *, label: str, scopes: list[str] | None = None) -> tuple[UUID, str]:
    """Mint an instance-scoped key for an instance admin; returns (key_id, token).

    Same discipline as mint_management_key, minus the org: instance reach is deliberate here
    rather than the absence of a scope. The caller checks the instance_admin bit before minting
    and verify_instance_key checks it again on every request. Runs inside the caller's transaction.
    """
    token = _new_key(INSTANCE_KEY_PREFIX)
    key = await InstanceKey(user_id=user_id, token_hash=token_hash(token), revoked=False, scopes=scopes, label=label).save()
    return key.id, token


async def mint_inference_key(org_id: UUID, workspace_id: UUID, user_id: UUID, *, label: str) -> tuple[UUID, str]:
    """Mint an inference API key row and its caller token; returns (key_id, token). Runs inside the caller's transaction."""
    token = _new_key(INFERENCE_TOKEN_PREFIX)
    key = await InferenceKey(
        org_id=org_id, workspace_id=workspace_id, user_id=user_id, token_hash=token_hash(token), revoked=False, label=label
    ).save()
    return key.id, token


async def verify_management_key(token: str) -> ManagementClaims | None:
    """Resolve a presented management key to org-scoped claims; returns None on any failure.

    One lookup by hash, then the backing checks: the row is not revoked and the owning user
    exists and still stands behind the key's org (instance admin, or membership in it).
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
    if not user.instance_admin and await OrgMembership.get((key.user_id, key.org_id)) is None:
        return None
    scopes = ALL_SCOPES if key.scopes is None else frozenset(key.scopes)
    return ManagementClaims(token_id=key.id, org_id=key.org_id, user_id=key.user_id, scopes=scopes)


async def verify_instance_key(token: str) -> ManagementClaims | None:
    """Resolve a presented instance key to instance-scoped claims; returns None on any failure.

    The instance_admin bit is rechecked here, not just at mint time, so demoting a user kills
    their instance keys on the next request the way losing a membership kills a management key.
    """
    if not token.startswith(INSTANCE_KEY_PREFIX):
        return None
    key = await InstanceKey.first(InstanceKey.token_hash == token_hash(token))
    if key is None or key.revoked:
        return None
    user = await User.find_by_id(key.user_id)
    if user is None or not user.instance_admin:
        return None
    scopes = ALL_SCOPES if key.scopes is None else frozenset(key.scopes)
    return ManagementClaims(token_id=key.id, org_id=None, user_id=key.user_id, scopes=scopes)


async def verify_bearer(token: str) -> ManagementClaims | None:
    """Resolve any presented bearer to backed claims, dispatching on the prefix it was minted with.

    The prefix picks the table, so a token can only ever be checked against the key type that
    issued it and one hash lookup answers the request.
    """
    if token.startswith(INSTANCE_KEY_PREFIX):
        return await verify_instance_key(token)
    return await verify_management_key(token)
