from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from contract import INFERENCE_TOKEN_PREFIX, token_hash
from control_plane.authz import Authority, Permission, Target
from control_plane.models import AccessKey, InferenceKey

if TYPE_CHECKING:
    from uuid import UUID

ACCESS_KEY_PREFIX = "sk-cp-"
PREFIX_SECRET_CHARS = 6


def key_prefix(token: str, kind: str) -> str:
    return token[: len(kind) + PREFIX_SECRET_CHARS]


def _new_key(kind: str) -> tuple[str, str]:
    token = kind + secrets.token_urlsafe(32)
    return token, key_prefix(token, kind)


@dataclass(frozen=True)
class AccessKeyGrant:
    principal_id: UUID
    target: Target
    permissions: frozenset[Permission]
    label: str
    expires_at: datetime | None = None
    parent_id: UUID | None = None


async def mint_access_key(grant: AccessKeyGrant) -> tuple[UUID, str]:
    token, prefix = _new_key(ACCESS_KEY_PREFIX)
    key = await AccessKey(
        user_id=grant.principal_id,
        org_id=grant.target.org_id,
        workspace_id=grant.target.workspace_id,
        parent_id=grant.parent_id,
        token_hash=token_hash(token),
        prefix=prefix,
        permissions=sorted(grant.permissions, key=str),
        label=grant.label,
        expires_at=grant.expires_at,
    ).save()
    return key.id, token


async def mint_inference_key(org_id: UUID, workspace_id: UUID, user_id: UUID, *, label: str) -> tuple[UUID, str]:
    token, prefix = _new_key(INFERENCE_TOKEN_PREFIX)
    key = await InferenceKey(
        org_id=org_id,
        workspace_id=workspace_id,
        user_id=user_id,
        token_hash=token_hash(token),
        prefix=prefix,
        revoked=False,
        label=label,
    ).save()
    return key.id, token


def _live(key: AccessKey, now: datetime) -> bool:
    return key.status(now) == "active"


async def verify_access_key(token: str) -> Authority | None:
    if not token.startswith(ACCESS_KEY_PREFIX):
        return None
    key = await AccessKey.first(AccessKey.token_hash == token_hash(token))
    now = datetime.now(tz=UTC)
    if key is None or not _live(key, now):
        return None
    seen = {key.id}
    parent_id = key.parent_id
    while parent_id is not None:
        if parent_id in seen:
            return None
        seen.add(parent_id)
        parent = await AccessKey.find_by_id(parent_id)
        if parent is None or not _live(parent, now):
            return None
        parent_id = parent.parent_id
    try:
        permissions = frozenset(Permission(value) for value in key.permissions)
    except ValueError:
        return None
    return Authority(
        credential_id=key.id,
        principal_id=key.user_id,
        credential_kind="access_key",
        boundary=key.boundary,
        org_id=key.org_id,
        workspace_id=key.workspace_id,
        permission_ceiling=permissions,
    )


async def verify_bearer(token: str) -> Authority | None:
    return await verify_access_key(token)
