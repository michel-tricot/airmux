from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from contract import INFERENCE_TOKEN_PREFIX, token_hash
from control_plane.authz import Actor, Grant, Permission, Scope
from control_plane.models import InferenceKey, ManagementKey, PlaygroundSession

if TYPE_CHECKING:
    from uuid import UUID

MANAGEMENT_KEY_PREFIX = "sk-cp-"
MIN_MANAGEMENT_KEY_SECRET_LENGTH = 32
MAX_MANAGEMENT_KEY_LENGTH = 512
PREFIX_SECRET_CHARS = 6
PLAYGROUND_SESSION_TTL = timedelta(minutes=5)


def key_prefix(token: str, kind: str) -> str:
    return token[: len(kind) + PREFIX_SECRET_CHARS]


def _new_key(kind: str) -> tuple[str, str]:
    token = kind + secrets.token_urlsafe(32)
    return token, key_prefix(token, kind)


def new_management_key() -> tuple[str, str]:
    return _new_key(MANAGEMENT_KEY_PREFIX)


def validate_management_key_token(token: str) -> str:
    if (
        not token.startswith(MANAGEMENT_KEY_PREFIX)
        or len(token) < len(MANAGEMENT_KEY_PREFIX) + MIN_MANAGEMENT_KEY_SECRET_LENGTH
        or len(token) > MAX_MANAGEMENT_KEY_LENGTH
    ):
        msg = "token must be a complete management key"
        raise ValueError(msg)
    return token


@dataclass(frozen=True)
class ManagementKeyGrant:
    principal_id: UUID
    scope: Scope
    permissions: frozenset[Permission]
    label: str
    expires_at: datetime | None = None
    parent_id: UUID | None = None


async def mint_management_key(grant: ManagementKeyGrant) -> tuple[UUID, str]:
    token, prefix = new_management_key()
    key = await ManagementKey(
        user_id=grant.principal_id,
        org_id=grant.scope.org_id,
        workspace_id=grant.scope.workspace_id,
        parent_id=grant.parent_id,
        token_hash=token_hash(token),
        prefix=prefix,
        permissions=sorted(grant.permissions, key=str),
        label=grant.label,
        expires_at=grant.expires_at,
    ).save()
    return key.id, token


async def mint_standing_management_key(principal_id: UUID, scope: Scope, label: str) -> tuple[UUID, str]:
    from control_plane.authority import principal_permissions  # noqa: PLC0415 authority loads management-key models

    return await mint_management_key(
        ManagementKeyGrant(
            principal_id=principal_id,
            scope=scope,
            permissions=await principal_permissions(principal_id, scope),
            label=label,
        )
    )


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


async def rotate_playground_session(
    org_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    credential_id: UUID,
    now: datetime,
) -> tuple[PlaygroundSession, str]:
    token, _ = _new_key(INFERENCE_TOKEN_PREFIX)
    playground_session = await PlaygroundSession.for_rotation(credential_id)
    if playground_session is None:
        playground_session = PlaygroundSession(
            org_id=org_id,
            workspace_id=workspace_id,
            user_id=user_id,
            credential_id=credential_id,
            token_hash=token_hash(token),
            expires_at=now + PLAYGROUND_SESSION_TTL,
            revoked=False,
        )
    else:
        playground_session.org_id = org_id
        playground_session.workspace_id = workspace_id
        playground_session.user_id = user_id
        playground_session.token_hash = token_hash(token)
        playground_session.expires_at = now + PLAYGROUND_SESSION_TTL
        playground_session.revoked = False
    return await playground_session.save(), token


def _live(key: ManagementKey, now: datetime) -> bool:
    return key.status(now) == "active"


async def verify_management_key(token: str) -> Actor | None:
    if not token.startswith(MANAGEMENT_KEY_PREFIX):
        return None
    key = await ManagementKey.first(ManagementKey.token_hash == token_hash(token))
    now = datetime.now(tz=UTC)
    if key is None or not _live(key, now):
        return None
    try:
        permissions = frozenset(Permission(value) for value in key.permissions)
    except ValueError:
        return None
    seen = {key.id}
    parent_id = key.parent_id
    while parent_id is not None:
        if parent_id in seen:
            return None
        seen.add(parent_id)
        parent = await ManagementKey.find_by_id(parent_id)
        if parent is None or not _live(parent, now):
            return None
        permissions &= frozenset(parent.permissions)
        parent_id = parent.parent_id
    return Actor(
        credential_id=key.id,
        principal_id=key.user_id,
        credential_kind="management_key",
        grant=Grant(scope=key.scope, permissions=permissions),
    )


async def verify_bearer(token: str) -> Actor | None:
    return await verify_management_key(token)
