from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScopeLevel(StrEnum):
    instance = "instance"
    org = "org"
    workspace = "workspace"


class Permission(StrEnum):
    organizations_read = "organizations.read"
    organizations_create = "organizations.create"
    organizations_update = "organizations.update"
    organizations_delete = "organizations.delete"
    principals_read = "principals.read"
    principals_manage = "principals.manage"
    members_read = "members.read"
    members_manage = "members.manage"
    workspaces_read = "workspaces.read"
    workspaces_create = "workspaces.create"
    workspaces_update = "workspaces.update"
    workspaces_delete = "workspaces.delete"
    catalog_read = "catalog.read"
    catalog_manage = "catalog.manage"
    provider_credentials_read = "provider-credentials.read"
    provider_credentials_manage = "provider-credentials.manage"
    inference_keys_read = "inference-keys.read"
    inference_keys_manage = "inference-keys.manage"
    playground_execute = "playground.execute"
    bundles_read = "bundles.read"
    bundles_publish = "bundles.publish"
    usage_read = "usage.read"
    usage_ingest = "usage.ingest"
    data_planes_read = "data-planes.read"
    data_planes_heartbeat = "data-planes.heartbeat"
    audit_read = "audit.read"
    access_keys_read = "access-keys.read"
    access_keys_issue = "access-keys.issue"
    access_keys_revoke = "access-keys.revoke"


class InstanceRole(StrEnum):
    owner = "owner"
    auditor = "auditor"
    data_plane = "data_plane"


class OrgRole(StrEnum):
    owner = "owner"
    admin = "admin"
    member = "member"
    data_plane = "data_plane"


class WorkspaceRole(StrEnum):
    admin = "admin"
    member = "member"
    viewer = "viewer"


ALL_PERMISSIONS = frozenset(Permission)
READ_PERMISSIONS = frozenset(
    {
        Permission.organizations_read,
        Permission.principals_read,
        Permission.members_read,
        Permission.workspaces_read,
        Permission.catalog_read,
        Permission.provider_credentials_read,
        Permission.inference_keys_read,
        Permission.bundles_read,
        Permission.usage_read,
        Permission.data_planes_read,
        Permission.audit_read,
        Permission.access_keys_read,
    }
)
DATA_PLANE_PERMISSIONS = frozenset(
    {
        Permission.bundles_read,
        Permission.usage_ingest,
        Permission.data_planes_heartbeat,
    }
)

INSTANCE_ROLE_PERMISSIONS = {
    InstanceRole.owner: ALL_PERMISSIONS,
    InstanceRole.auditor: READ_PERMISSIONS,
    InstanceRole.data_plane: DATA_PLANE_PERMISSIONS,
}
ORG_ROLE_PERMISSIONS = {
    OrgRole.owner: frozenset(
        {
            Permission.organizations_read,
            Permission.organizations_update,
            Permission.organizations_delete,
            Permission.members_read,
            Permission.members_manage,
            Permission.workspaces_read,
            Permission.workspaces_create,
            Permission.workspaces_update,
            Permission.workspaces_delete,
            Permission.catalog_read,
            Permission.provider_credentials_read,
            Permission.provider_credentials_manage,
            Permission.inference_keys_read,
            Permission.inference_keys_manage,
            Permission.playground_execute,
            Permission.bundles_read,
            Permission.bundles_publish,
            Permission.usage_read,
            Permission.audit_read,
            Permission.access_keys_read,
            Permission.access_keys_issue,
            Permission.access_keys_revoke,
        }
    ),
    OrgRole.admin: frozenset(
        {
            Permission.organizations_read,
            Permission.organizations_update,
            Permission.members_read,
            Permission.members_manage,
            Permission.workspaces_read,
            Permission.workspaces_create,
            Permission.workspaces_update,
            Permission.workspaces_delete,
            Permission.catalog_read,
            Permission.provider_credentials_read,
            Permission.provider_credentials_manage,
            Permission.inference_keys_read,
            Permission.inference_keys_manage,
            Permission.playground_execute,
            Permission.bundles_read,
            Permission.bundles_publish,
            Permission.usage_read,
            Permission.audit_read,
            Permission.access_keys_read,
            Permission.access_keys_issue,
            Permission.access_keys_revoke,
        }
    ),
    OrgRole.member: frozenset(
        {
            Permission.organizations_read,
            Permission.workspaces_create,
            Permission.catalog_read,
        }
    ),
    OrgRole.data_plane: DATA_PLANE_PERMISSIONS,
}
WORKSPACE_ROLE_PERMISSIONS = {
    WorkspaceRole.admin: frozenset(
        {
            Permission.workspaces_read,
            Permission.workspaces_update,
            Permission.workspaces_delete,
            Permission.members_read,
            Permission.members_manage,
            Permission.catalog_read,
            Permission.provider_credentials_read,
            Permission.provider_credentials_manage,
            Permission.inference_keys_read,
            Permission.inference_keys_manage,
            Permission.playground_execute,
            Permission.usage_read,
            Permission.access_keys_read,
            Permission.access_keys_issue,
            Permission.access_keys_revoke,
        }
    ),
    WorkspaceRole.member: frozenset(
        {
            Permission.workspaces_read,
            Permission.members_read,
            Permission.catalog_read,
            Permission.provider_credentials_read,
            Permission.inference_keys_read,
            Permission.inference_keys_manage,
            Permission.playground_execute,
            Permission.usage_read,
        }
    ),
    WorkspaceRole.viewer: frozenset(
        {
            Permission.workspaces_read,
            Permission.members_read,
            Permission.catalog_read,
            Permission.provider_credentials_read,
            Permission.inference_keys_read,
            Permission.usage_read,
        }
    ),
}


def permissions_for_org_role(role: OrgRole) -> frozenset[Permission]:
    return ORG_ROLE_PERMISSIONS[role]


class Scope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    level: ScopeLevel
    org_id: UUID | None = None
    workspace_id: UUID | None = None

    @model_validator(mode="before")
    @classmethod
    def require_concrete_scope(cls, value: object) -> object:
        if cls is Scope:
            msg = "use an instance, organization, or workspace scope"
            raise ValueError(msg)
        return value

    def covers(self, target: ScopeValue) -> bool:
        if self.level is ScopeLevel.instance:
            return True
        if self.level is ScopeLevel.org:
            return self.org_id == target.org_id and target.level is not ScopeLevel.instance
        return target.level is ScopeLevel.workspace and self.org_id == target.org_id and self.workspace_id == target.workspace_id

    @classmethod
    def instance(cls) -> InstanceScope:
        return InstanceScope()

    @classmethod
    def org(cls, org_id: UUID) -> OrgScope:
        return OrgScope(org_id=org_id)

    @classmethod
    def workspace(cls, org_id: UUID, workspace_id: UUID) -> WorkspaceScope:
        return WorkspaceScope(org_id=org_id, workspace_id=workspace_id)


class InstanceScope(Scope):
    level: Literal[ScopeLevel.instance] = ScopeLevel.instance
    org_id: None = None
    workspace_id: None = None


class OrgScope(Scope):
    level: Literal[ScopeLevel.org] = ScopeLevel.org
    org_id: UUID
    workspace_id: None = None


class WorkspaceScope(Scope):
    level: Literal[ScopeLevel.workspace] = ScopeLevel.workspace
    org_id: UUID
    workspace_id: UUID


ScopeValue = Annotated[InstanceScope | OrgScope | WorkspaceScope, Field(discriminator="level")]


class Grant(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: ScopeValue
    permissions: frozenset[Permission]


class Actor(BaseModel):
    model_config = ConfigDict(frozen=True)

    credential_id: UUID
    principal_id: UUID
    credential_kind: str
    grant: Grant


class AccessRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    permission: Permission
    target: ScopeValue


class Decision(StrEnum):
    allow = "allow"
    credential_scope = "credential_scope"
    credential_ceiling = "credential_ceiling"
    standing_authority = "standing_authority"


def decide(actor: Actor, standing: tuple[Grant, ...], request: AccessRequest) -> Decision:
    if not actor.grant.scope.covers(request.target):
        return Decision.credential_scope
    if request.permission not in actor.grant.permissions:
        return Decision.credential_ceiling
    if not any(grant.scope.covers(request.target) and request.permission in grant.permissions for grant in standing):
        return Decision.standing_authority
    return Decision.allow
