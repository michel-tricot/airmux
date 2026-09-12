from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlmodel import col

from contract import token_hash
from control_plane.authz import DATA_PLANE_PERMISSIONS, InstanceRole
from control_plane.db import current_session
from control_plane.keys import MANAGEMENT_KEY_PREFIX, key_prefix
from control_plane.models import ManagementKey, User, set_actor

if TYPE_CHECKING:
    from control_plane.config import DataPlaneBootstrap

_BOOTSTRAP_LOCK = 0x41524450
_BOOTSTRAP_NAME = "deployment data plane"


async def bootstrap_data_plane(bootstrap: DataPlaneBootstrap) -> None:
    await current_session().execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _BOOTSTRAP_LOCK})
    token = bootstrap.token.get_secret_value()
    token_digest = token_hash(token)
    existing = await ManagementKey.first(ManagementKey.token_hash == token_digest)
    if existing is not None:
        await _validate_existing(existing)
        return
    initialized = await User.first(User.name == _BOOTSTRAP_NAME, col(User.service_account).is_(True))
    if initialized is not None:
        msg = "the configured data-plane bootstrap token does not match the initialized pool key"
        raise RuntimeError(msg)
    if not await User.reserve_unclaimed_instance():
        msg = "cannot bootstrap a data-plane key after the instance is already claimed"
        raise RuntimeError(msg)
    await set_actor("root")
    user = await User.new_service_account(_BOOTSTRAP_NAME, instance_role=InstanceRole.data_plane).save()
    await ManagementKey(
        user_id=user.id,
        token_hash=token_digest,
        prefix=key_prefix(token, MANAGEMENT_KEY_PREFIX),
        permissions=sorted(DATA_PLANE_PERMISSIONS, key=str),
        label=_BOOTSTRAP_NAME,
    ).save()


async def _validate_existing(key: ManagementKey) -> None:
    if key.revoked_at is not None:
        msg = "the configured data-plane bootstrap key is revoked"
        raise RuntimeError(msg)
    if key.expires_at is not None and key.expires_at <= datetime.now(tz=UTC):
        msg = "the configured data-plane bootstrap key is expired"
        raise RuntimeError(msg)
    user = await User.find_by_id(key.user_id)
    valid = (
        user is not None
        and user.service_account
        and user.instance_role == InstanceRole.data_plane
        and key.org_id is None
        and key.workspace_id is None
        and key.parent_id is None
        and set(key.permissions) == DATA_PLANE_PERMISSIONS
    )
    if not valid:
        msg = "the configured data-plane bootstrap token belongs to a different authority"
        raise RuntimeError(msg)
