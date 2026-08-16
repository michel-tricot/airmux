from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col

from control_plane.authz import Boundary, Permission, Target, principal_permissions
from control_plane.deps import AuthorityDep, OrgHeader, require
from control_plane.keys import AccessKeyGrant, mint_access_key
from control_plane.models import AccessKey, Org, User, Workspace
from control_plane.models.access_key import AccessKeyIn, AccessKeyMintedOut, AccessKeyOut, AccessKeyRevokedOut
from control_plane.models.common.wire import Envelope

router = APIRouter(prefix="/access-keys", tags=["Access Keys"])


async def _existing_target(target: Target) -> Target:
    if target.org_id is not None and await Org.find_by_id(target.org_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if target.workspace_id is not None:
        org_id = target.org_id
        if org_id is None:
            raise HTTPException(status_code=422, detail="workspace_id requires org_id")
        await Workspace.owned_by(org_id, target.workspace_id)
    return target


async def access_key_create_target(body: AccessKeyIn, authority: AuthorityDep) -> Target:
    if body.org_id is None and body.workspace_id is None and authority.boundary is not None:
        return Target(level=authority.boundary, org_id=authority.org_id, workspace_id=authority.workspace_id)
    return await _existing_target(body.target)


async def access_key_list_target(
    authority: AuthorityDep,
    org_id: UUID | None = None,
    workspace_id: UUID | None = None,
    x_org_id: OrgHeader = None,
) -> Target:
    if workspace_id is not None and org_id is None:
        raise HTTPException(status_code=422, detail="workspace_id requires org_id")
    if workspace_id is not None and org_id is not None:
        return await _existing_target(Target.workspace(org_id, workspace_id))
    if org_id is not None:
        return await _existing_target(Target.org(org_id))
    if authority.boundary is not None:
        return Target(level=authority.boundary, org_id=authority.org_id, workspace_id=authority.workspace_id)
    if x_org_id is not None:
        try:
            return await _existing_target(Target.org(UUID(x_org_id)))
        except ValueError:
            raise HTTPException(status_code=403, detail="X-Org-Id is not a valid organization id") from None
    return Target.instance()


async def selected_access_key(key_id: UUID) -> AccessKey:
    key = await AccessKey.find_by_id(key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="Access key not found")
    return key


AccessKeyDep = Annotated[AccessKey, Depends(selected_access_key)]


async def access_key_target(key: AccessKeyDep) -> Target:
    return key.target


def _out(key: AccessKey, now: datetime) -> AccessKeyOut:
    return AccessKeyOut.model_validate({**key.model_dump(), "boundary": key.boundary, "status": key.status(now)})


@router.get("", dependencies=[require(Permission.access_keys_read, access_key_list_target)])
async def list_access_keys(
    target: Annotated[Target, Depends(access_key_list_target)],
    user_id: UUID | None = None,
) -> Envelope[list[AccessKeyOut]]:
    conditions = []
    if target.level is Boundary.org:
        conditions.append(AccessKey.org_id == target.org_id)
    elif target.level is Boundary.workspace:
        conditions.extend((AccessKey.org_id == target.org_id, AccessKey.workspace_id == target.workspace_id))
    if user_id is not None:
        conditions.append(AccessKey.user_id == user_id)
    keys = await AccessKey.find(*conditions, order_by=col(AccessKey.id))
    now = datetime.now(tz=UTC)
    return Envelope(data=[_out(key, now) for key in keys])


@router.post("", dependencies=[require(Permission.access_keys_issue, access_key_create_target)])
async def create_access_key(
    body: AccessKeyIn,
    authority: AuthorityDep,
    target: Annotated[Target, Depends(access_key_create_target)],
) -> Envelope[AccessKeyMintedOut]:
    now = datetime.now(tz=UTC)
    if body.expires_at is not None and body.expires_at <= now:
        raise HTTPException(status_code=422, detail="expires_at must be in the future")
    user_id = body.user_id or authority.principal_id
    user = await User.find_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Principal not found")
    permissions = frozenset(body.permissions)
    available = await principal_permissions(user_id, target)
    if not permissions <= available:
        raise HTTPException(status_code=403, detail="Requested permissions exceed the principal's standing authority")
    issuer_permissions = await principal_permissions(authority.principal_id, target)
    if not permissions <= issuer_permissions:
        raise HTTPException(status_code=403, detail="Requested permissions exceed the acting principal's standing authority")
    parent_id = None
    if authority.credential_kind == "access_key":
        if Permission.access_keys_issue in permissions:
            raise HTTPException(status_code=403, detail="A delegated key cannot delegate access-key issuance")
        if not permissions < authority.permission_ceiling:
            raise HTTPException(status_code=403, detail="A delegated key must carry strictly less authority than its issuer")
        parent = await AccessKey.find_by_id(authority.credential_id)
        if parent is None:
            raise HTTPException(status_code=401, detail="Issuing credential no longer exists")
        if parent.expires_at is not None and (body.expires_at is None or body.expires_at > parent.expires_at):
            raise HTTPException(status_code=403, detail="A delegated key cannot outlive its issuer")
        parent_id = parent.id
    key_id, token = await mint_access_key(
        AccessKeyGrant(
            principal_id=user_id,
            target=target,
            permissions=permissions,
            label=body.label,
            expires_at=body.expires_at,
            parent_id=parent_id,
        )
    )
    key = await AccessKey.find_by_id(key_id)
    if key is None:
        raise HTTPException(status_code=500, detail="Access key was not persisted")
    return Envelope(data=AccessKeyMintedOut.model_validate({**key.model_dump(), "boundary": key.boundary, "status": key.status(now), "token": token}))


@router.delete("/{key_id}", dependencies=[require(Permission.access_keys_revoke, access_key_target)])
async def revoke_access_key(key: AccessKeyDep) -> Envelope[AccessKeyRevokedOut]:
    revoked_at = datetime.now(tz=UTC)
    await key.revoke_with_descendants(revoked_at)
    return Envelope(data=AccessKeyRevokedOut(id=key.id, status="revoked", revoked_at=revoked_at))
