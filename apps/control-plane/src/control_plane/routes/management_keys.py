from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col

from control_plane.authority import ensure_management_key_permissions, management_key_parent
from control_plane.authz import Actor, Permission, Scope, ScopeLevel
from control_plane.deps import ActorDep, OrgDep, WorkspaceDep, instance_scope, org_scope, require, workspace_scope
from control_plane.keys import ManagementKeyGrant, create_management_key
from control_plane.models import ManagementKey
from control_plane.models.common.wire import Envelope
from control_plane.models.management_key import (
    ManagementKeyCreatedOut,
    ManagementKeyIn,
    ManagementKeyOut,
    ManagementKeyPermissionsIn,
    ManagementKeyRevokedOut,
)

router = APIRouter()


async def selected_management_key(key_id: UUID) -> ManagementKey:
    key = await ManagementKey.find_by_id(key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="Management key not found")
    return key


ManagementKeyDep = Annotated[ManagementKey, Depends(selected_management_key)]


async def management_key_scope(key: ManagementKeyDep) -> Scope:
    return key.scope


def _out(key: ManagementKey, now: datetime) -> ManagementKeyOut:
    return ManagementKeyOut.model_validate({**key.model_dump(), "scope": key.scope, "status": key.status(now)})


async def _list_management_keys(scope: Scope, user_id: UUID | None) -> Envelope[list[ManagementKeyOut]]:
    conditions = []
    if scope.level is ScopeLevel.org:
        conditions.append(ManagementKey.org_id == scope.org_id)
    elif scope.level is ScopeLevel.workspace:
        conditions.extend((ManagementKey.org_id == scope.org_id, ManagementKey.workspace_id == scope.workspace_id))
    if user_id is not None:
        conditions.append(ManagementKey.user_id == user_id)
    keys = await ManagementKey.find(*conditions, order_by=col(ManagementKey.id))
    now = datetime.now(tz=UTC)
    return Envelope(data=[_out(key, now) for key in keys])


async def issue_management_key(body: ManagementKeyIn, actor: Actor, scope: Scope, *, principal_id: UUID) -> ManagementKeyCreatedOut:
    now = datetime.now(tz=UTC)
    if body.expires_at is not None and body.expires_at <= now:
        raise HTTPException(status_code=422, detail="expires_at must be in the future")
    permissions = frozenset(body.permissions)
    parent_id = await management_key_parent(actor, principal_id, scope, permissions, body.expires_at)
    key_id, token = await create_management_key(
        ManagementKeyGrant(
            principal_id=principal_id,
            scope=scope,
            permissions=permissions,
            label=body.label,
            expires_at=body.expires_at,
            parent_id=parent_id,
        )
    )
    key = await ManagementKey.find_by_id(key_id)
    if key is None:
        raise HTTPException(status_code=500, detail="Management key was not persisted")
    return ManagementKeyCreatedOut.model_validate({**key.model_dump(), "scope": key.scope, "status": key.status(now), "token": token})


async def _create_management_key(body: ManagementKeyIn, actor: Actor, scope: Scope) -> Envelope[ManagementKeyCreatedOut]:
    return Envelope(data=await issue_management_key(body, actor, scope, principal_id=actor.principal_id))


@router.get(
    "/instance/management-keys", tags=["Instance Management Keys"], dependencies=[require("api", instance_scope, Permission.management_keys_read)]
)
async def list_instance_management_keys(user_id: UUID | None = None) -> Envelope[list[ManagementKeyOut]]:
    """List management keys across all scopes, optionally filtered by principal."""
    return await _list_management_keys(Scope.instance(), user_id)


@router.post(
    "/instance/management-keys", tags=["Instance Management Keys"], dependencies=[require("api", instance_scope, Permission.management_keys_issue)]
)
async def create_instance_management_key(body: ManagementKeyIn, actor: ActorDep) -> Envelope[ManagementKeyCreatedOut]:
    """Create an instance-scoped management key and return its token once."""
    return await _create_management_key(body, actor, Scope.instance())


@router.get(
    "/organizations/{org_id}/management-keys",
    tags=["Organization Management Keys"],
    dependencies=[require("api", org_scope, Permission.management_keys_read)],
)
async def list_org_management_keys(org_id: OrgDep, user_id: UUID | None = None) -> Envelope[list[ManagementKeyOut]]:
    """List organization- and workspace-scoped management keys within an organization."""
    return await _list_management_keys(Scope.org(org_id), user_id)


@router.post(
    "/organizations/{org_id}/management-keys",
    tags=["Organization Management Keys"],
    dependencies=[require("api", org_scope, Permission.management_keys_issue)],
)
async def create_org_management_key(body: ManagementKeyIn, org_id: OrgDep, actor: ActorDep) -> Envelope[ManagementKeyCreatedOut]:
    """Create an organization-scoped management key and return its token once."""
    return await _create_management_key(body, actor, Scope.org(org_id))


@router.get(
    "/organizations/{org_id}/workspaces/{workspace_ref}/management-keys",
    tags=["Workspace Management Keys"],
    dependencies=[require("api", workspace_scope, Permission.management_keys_read)],
)
async def list_workspace_management_keys(workspace: WorkspaceDep, user_id: UUID | None = None) -> Envelope[list[ManagementKeyOut]]:
    """List management keys scoped to one workspace."""
    return await _list_management_keys(Scope.workspace(workspace.org_id, workspace.id), user_id)


@router.post(
    "/organizations/{org_id}/workspaces/{workspace_ref}/management-keys",
    tags=["Workspace Management Keys"],
    dependencies=[require("api", workspace_scope, Permission.management_keys_issue)],
)
async def create_workspace_management_key(body: ManagementKeyIn, workspace: WorkspaceDep, actor: ActorDep) -> Envelope[ManagementKeyCreatedOut]:
    """Create a workspace-scoped management key and return its token once."""
    return await _create_management_key(body, actor, Scope.workspace(workspace.org_id, workspace.id))


@router.delete(
    "/management-keys/{key_id}",
    tags=["Instance Management Keys", "Organization Management Keys", "Workspace Management Keys"],
    dependencies=[require("api", management_key_scope, Permission.management_keys_revoke)],
)
async def revoke_management_key(key: ManagementKeyDep) -> Envelope[ManagementKeyRevokedOut]:
    """Revoke an management key and every key delegated from it."""
    revoked_at = datetime.now(tz=UTC)
    await key.revoke_with_descendants(revoked_at)
    return Envelope(data=ManagementKeyRevokedOut(id=key.id, status="revoked", revoked_at=revoked_at))


@router.put(
    "/management-keys/{key_id}/permissions",
    tags=["Instance Management Keys", "Organization Management Keys", "Workspace Management Keys"],
    dependencies=[require("api", management_key_scope, Permission.management_keys_issue)],
)
async def update_management_key_permissions(body: ManagementKeyPermissionsIn, key: ManagementKeyDep, actor: ActorDep) -> Envelope[ManagementKeyOut]:
    now = datetime.now(tz=UTC)
    if key.status(now) != "active":
        raise HTTPException(status_code=409, detail="Only active management keys can have their permissions changed")
    permissions = frozenset(body.permissions)
    await ensure_management_key_permissions(actor, key, permissions, now)
    key.permissions = sorted(permissions, key=str)
    await key.save()
    return Envelope(data=_out(key, now))
