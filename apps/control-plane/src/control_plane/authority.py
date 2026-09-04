from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import col

from control_plane.authz import (
    INSTANCE_ROLE_PERMISSIONS,
    ORG_ROLE_PERMISSIONS,
    WORKSPACE_ROLE_PERMISSIONS,
    AccessRequest,
    Actor,
    Decision,
    Grant,
    InstanceRole,
    OrgRole,
    Permission,
    Scope,
    ScopeLevel,
    WorkspaceRole,
    decide,
)
from control_plane.models import AccessKey, OrgMembership, User, Workspace, WorkspaceMembership

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime
    from uuid import UUID


class AuthorizationError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail


class CredentialError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail


async def standing_grants(principal_id: UUID, targets: Iterable[Scope]) -> tuple[Grant, ...]:
    scopes = frozenset(targets)
    user = await User.find_by_id(principal_id)
    if user is None:
        return ()
    grants = (
        (Grant(scope=Scope.instance(), permissions=INSTANCE_ROLE_PERMISSIONS[InstanceRole(user.instance_role)]),)
        if user.instance_role is not None
        else ()
    )
    org_ids = frozenset(scope.org_id for scope in scopes if scope.org_id is not None)
    if org_ids:
        memberships = await OrgMembership.find(OrgMembership.user_id == principal_id, col(OrgMembership.org_id).in_(org_ids))
        grants += tuple(
            Grant(scope=Scope.org(membership.org_id), permissions=ORG_ROLE_PERMISSIONS[OrgRole(membership.role)]) for membership in memberships
        )
    workspace_ids = frozenset(scope.workspace_id for scope in scopes if scope.workspace_id is not None)
    if workspace_ids:
        memberships = await WorkspaceMembership.find(
            WorkspaceMembership.user_id == principal_id,
            col(WorkspaceMembership.workspace_id).in_(workspace_ids),
        )
        grants += tuple(
            Grant(
                scope=Scope.workspace(membership.org_id, membership.workspace_id),
                permissions=WORKSPACE_ROLE_PERMISSIONS[WorkspaceRole(membership.role)],
            )
            for membership in memberships
        )
    return grants


async def decision(actor: Actor, permission: Permission, target: Scope) -> Decision:
    return decide(actor, await standing_grants(actor.principal_id, (target,)), AccessRequest(permission=permission, target=target))


async def decisions(actor: Actor, permission: Permission, targets: Iterable[Scope]) -> dict[Scope, Decision]:
    scopes = frozenset(targets)
    grants = await standing_grants(actor.principal_id, scopes)
    return {scope: decide(actor, grants, AccessRequest(permission=permission, target=scope)) for scope in scopes}


async def readable_workspaces(actor: Actor, org_id: UUID) -> list[Workspace]:
    if Permission.workspaces_read not in actor.grant.permissions or not actor.grant.scope.covers(Scope.org(org_id)):
        return []
    return await Workspace.readable_by(
        actor.principal_id,
        org_id,
        instance_roles=tuple(role.value for role, permissions in INSTANCE_ROLE_PERMISSIONS.items() if Permission.workspaces_read in permissions),
        org_roles=tuple(role.value for role, permissions in ORG_ROLE_PERMISSIONS.items() if Permission.workspaces_read in permissions),
        workspace_roles=tuple(role.value for role, permissions in WORKSPACE_ROLE_PERMISSIONS.items() if Permission.workspaces_read in permissions),
    )


async def is_allowed(actor: Actor, permission: Permission, target: Scope) -> bool:
    return await decision(actor, permission, target) is Decision.allow


async def ensure_allowed(actor: Actor, permission: Permission, target: Scope) -> None:
    if not await is_allowed(actor, permission, target):
        detail = f"Missing {permission.value} permission for {target.level.value} scope"
        raise AuthorizationError(detail)


async def ensure_allowed_for_scopes(actor: Actor, permission: Permission, targets: Iterable[Scope]) -> None:
    results = await decisions(actor, permission, targets)
    denied = next((scope for scope, result in results.items() if result is not Decision.allow), None)
    if denied is not None:
        detail = f"Missing {permission.value} permission for {denied.level.value} scope"
        raise AuthorizationError(detail)


async def principal_permissions(principal_id: UUID, target: Scope) -> frozenset[Permission]:
    grants = await standing_grants(principal_id, (target,))
    return frozenset(permission for grant in grants if grant.scope.covers(target) for permission in grant.permissions)


async def effective_permissions(actor: Actor, target: Scope) -> frozenset[Permission]:
    if not actor.grant.scope.covers(target):
        return frozenset()
    return await principal_permissions(actor.principal_id, target) & actor.grant.permissions


async def can_assign_org_role(actor: Actor, org_id: UUID, current: str | None, desired: OrgRole) -> bool:
    user = await User.find_by_id(actor.principal_id)
    if user is None:
        return False
    if user.instance_role == InstanceRole.owner:
        return True
    membership = await OrgMembership.get((actor.principal_id, org_id))
    if membership is None:
        return False
    role = OrgRole(membership.role)
    return role is OrgRole.owner or (role is OrgRole.admin and current != OrgRole.owner and desired is not OrgRole.owner)


async def ensure_org_role_change(actor: Actor, org_id: UUID, current: str | None, desired: OrgRole) -> None:
    await ensure_allowed(actor, Permission.members_manage, Scope.org(org_id))
    if not await can_assign_org_role(actor, org_id, current, desired):
        detail = "You cannot assign that organization role"
        raise AuthorizationError(detail)


def visible_org_ids(actor: Actor, org_ids: Iterable[UUID]) -> list[UUID]:
    visible = sorted(org_ids)
    if actor.grant.scope.level in {ScopeLevel.org, ScopeLevel.workspace}:
        visible = [org_id for org_id in visible if org_id == actor.grant.scope.org_id]
    return visible


async def principal_can_select_org(principal_id: UUID, org_id: UUID) -> bool:
    user = await User.find_by_id(principal_id)
    return user is not None and (user.instance_role is not None or await OrgMembership.get((principal_id, org_id)) is not None)


async def principal_can_issue_instance_access_key(principal_id: UUID) -> bool:
    return Permission.access_keys_issue in await principal_permissions(principal_id, Scope.instance())


async def access_key_parent(
    actor: Actor,
    principal_id: UUID,
    scope: Scope,
    permissions: frozenset[Permission],
    expires_at: datetime | None,
) -> UUID | None:
    await ensure_allowed(actor, Permission.access_keys_issue, scope)
    if not permissions <= await principal_permissions(principal_id, scope):
        detail = "Requested permissions exceed the target principal's current permissions"
        raise AuthorizationError(detail)
    if not permissions <= await principal_permissions(actor.principal_id, scope):
        detail = "Requested permissions exceed your current permissions"
        raise AuthorizationError(detail)
    if actor.credential_kind != "access_key":
        return None
    if Permission.access_keys_issue in permissions:
        detail = "A delegated key cannot delegate access-key issuance"
        raise AuthorizationError(detail)
    if not permissions < actor.grant.permissions:
        detail = "A delegated key must carry strictly fewer permissions than its issuer"
        raise AuthorizationError(detail)
    parent = await AccessKey.find_by_id(actor.credential_id)
    if parent is None:
        detail = "Issuing credential no longer exists"
        raise CredentialError(detail)
    if parent.expires_at is not None and (expires_at is None or expires_at > parent.expires_at):
        detail = "A delegated key cannot outlive its issuer"
        raise AuthorizationError(detail)
    return parent.id
