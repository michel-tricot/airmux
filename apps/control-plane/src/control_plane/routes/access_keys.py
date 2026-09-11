from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col

from control_plane.authority import access_key_parent, ensure_access_key_permissions
from control_plane.authz import Actor, Permission, Scope, ScopeLevel
from control_plane.deps import ActorDep, OrgDep, WorkspaceDep, instance_scope, org_scope, require, workspace_scope
from control_plane.keys import AccessKeyGrant, mint_access_key
from control_plane.models import AccessKey, User
from control_plane.models.access_key import AccessKeyIn, AccessKeyMintedOut, AccessKeyOut, AccessKeyPermissionsIn, AccessKeyRevokedOut
from control_plane.models.common.wire import Envelope

router = APIRouter()


async def selected_access_key(key_id: UUID) -> AccessKey:
    key = await AccessKey.find_by_id(key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="Access key not found")
    return key


AccessKeyDep = Annotated[AccessKey, Depends(selected_access_key)]


async def access_key_scope(key: AccessKeyDep) -> Scope:
    return key.scope


def _out(key: AccessKey, now: datetime) -> AccessKeyOut:
    return AccessKeyOut.model_validate({**key.model_dump(), "scope": key.scope, "status": key.status(now)})


async def _list_access_keys(scope: Scope, user_id: UUID | None) -> Envelope[list[AccessKeyOut]]:
    conditions = []
    if scope.level is ScopeLevel.org:
        conditions.append(AccessKey.org_id == scope.org_id)
    elif scope.level is ScopeLevel.workspace:
        conditions.extend((AccessKey.org_id == scope.org_id, AccessKey.workspace_id == scope.workspace_id))
    if user_id is not None:
        conditions.append(AccessKey.user_id == user_id)
    keys = await AccessKey.find(*conditions, order_by=col(AccessKey.id))
    now = datetime.now(tz=UTC)
    return Envelope(data=[_out(key, now) for key in keys])


async def issue_access_key(body: AccessKeyIn, actor: Actor, scope: Scope) -> AccessKeyMintedOut:
    now = datetime.now(tz=UTC)
    if body.expires_at is not None and body.expires_at <= now:
        raise HTTPException(status_code=422, detail="expires_at must be in the future")
    principal_id = body.user_id or actor.principal_id
    if await User.find_by_id(principal_id) is None:
        raise HTTPException(status_code=404, detail="Principal not found")
    permissions = frozenset(body.permissions)
    parent_id = await access_key_parent(actor, principal_id, scope, permissions, body.expires_at)
    key_id, token = await mint_access_key(
        AccessKeyGrant(
            principal_id=principal_id,
            scope=scope,
            permissions=permissions,
            label=body.label,
            expires_at=body.expires_at,
            parent_id=parent_id,
        )
    )
    key = await AccessKey.find_by_id(key_id)
    if key is None:
        raise HTTPException(status_code=500, detail="Access key was not persisted")
    return AccessKeyMintedOut.model_validate({**key.model_dump(), "scope": key.scope, "status": key.status(now), "token": token})


async def _create_access_key(body: AccessKeyIn, actor: Actor, scope: Scope) -> Envelope[AccessKeyMintedOut]:
    return Envelope(data=await issue_access_key(body, actor, scope))


@router.get("/instance/access-keys", tags=["Instance Access Keys"], dependencies=[require(instance_scope, Permission.access_keys_read)])
async def list_instance_access_keys(user_id: UUID | None = None) -> Envelope[list[AccessKeyOut]]:
    """List access keys across all scopes, optionally filtered by principal."""
    return await _list_access_keys(Scope.instance(), user_id)


@router.post("/instance/access-keys", tags=["Instance Access Keys"], dependencies=[require(instance_scope, Permission.access_keys_issue)])
async def create_instance_access_key(body: AccessKeyIn, actor: ActorDep) -> Envelope[AccessKeyMintedOut]:
    """Issue an instance-scoped access key and return its token once."""
    return await _create_access_key(body, actor, Scope.instance())


@router.get("/orgs/{org_id}/access-keys", tags=["Organization Access Keys"], dependencies=[require(org_scope, Permission.access_keys_read)])
async def list_org_access_keys(org_id: OrgDep, user_id: UUID | None = None) -> Envelope[list[AccessKeyOut]]:
    """List organization- and workspace-scoped access keys within an organization."""
    return await _list_access_keys(Scope.org(org_id), user_id)


@router.post("/orgs/{org_id}/access-keys", tags=["Organization Access Keys"], dependencies=[require(org_scope, Permission.access_keys_issue)])
async def create_org_access_key(body: AccessKeyIn, org_id: OrgDep, actor: ActorDep) -> Envelope[AccessKeyMintedOut]:
    """Issue an organization-scoped access key and return its token once."""
    return await _create_access_key(body, actor, Scope.org(org_id))


@router.get(
    "/orgs/{org_id}/workspaces/{workspace_ref}/access-keys",
    tags=["Workspace Access Keys"],
    dependencies=[require(workspace_scope, Permission.access_keys_read)],
)
async def list_workspace_access_keys(workspace: WorkspaceDep, user_id: UUID | None = None) -> Envelope[list[AccessKeyOut]]:
    """List access keys scoped to one workspace."""
    return await _list_access_keys(Scope.workspace(workspace.org_id, workspace.id), user_id)


@router.post(
    "/orgs/{org_id}/workspaces/{workspace_ref}/access-keys",
    tags=["Workspace Access Keys"],
    dependencies=[require(workspace_scope, Permission.access_keys_issue)],
)
async def create_workspace_access_key(body: AccessKeyIn, workspace: WorkspaceDep, actor: ActorDep) -> Envelope[AccessKeyMintedOut]:
    """Issue a workspace-scoped access key and return its token once."""
    return await _create_access_key(body, actor, Scope.workspace(workspace.org_id, workspace.id))


@router.delete(
    "/access-keys/{key_id}",
    tags=["Instance Access Keys", "Organization Access Keys", "Workspace Access Keys"],
    dependencies=[require(access_key_scope, Permission.access_keys_revoke)],
)
async def revoke_access_key(key: AccessKeyDep) -> Envelope[AccessKeyRevokedOut]:
    """Revoke an access key and every key delegated from it."""
    revoked_at = datetime.now(tz=UTC)
    await key.revoke_with_descendants(revoked_at)
    return Envelope(data=AccessKeyRevokedOut(id=key.id, status="revoked", revoked_at=revoked_at))


@router.put(
    "/access-keys/{key_id}/permissions",
    tags=["Instance Access Keys", "Organization Access Keys", "Workspace Access Keys"],
    dependencies=[require(access_key_scope, Permission.access_keys_issue)],
)
async def update_access_key_permissions(body: AccessKeyPermissionsIn, key: AccessKeyDep, actor: ActorDep) -> Envelope[AccessKeyOut]:
    now = datetime.now(tz=UTC)
    if key.status(now) != "active":
        raise HTTPException(status_code=409, detail="Only active management keys can have their permissions changed")
    permissions = frozenset(body.permissions)
    await ensure_access_key_permissions(actor, key, permissions, now)
    key.permissions = sorted(permissions, key=str)
    await key.save()
    return Envelope(data=_out(key, now))
