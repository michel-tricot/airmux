from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

if TYPE_CHECKING:
    from typing import Self


class Boundary(StrEnum):
    instance = "instance"
    org = "org"
    workspace = "workspace"

    def covers(self, org_id: UUID | None, workspace_id: UUID | None, target: Target) -> bool:
        if self is Boundary.instance:
            return True
        if self is Boundary.org:
            return org_id == target.org_id and workspace_id is None and target.level is not Boundary.instance
        return target.level is Boundary.workspace and org_id == target.org_id and workspace_id == target.workspace_id


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
            Permission.workspaces_read,
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


def permissions_for_org_role(role: OrgRole | str) -> frozenset[Permission]:
    return ORG_ROLE_PERMISSIONS[OrgRole(role)]


class Target(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: Boundary
    org_id: UUID | None = None
    workspace_id: UUID | None = None

    @model_validator(mode="after")
    def valid_boundary(self) -> Self:
        expected = {
            Boundary.instance: (False, False),
            Boundary.org: (True, False),
            Boundary.workspace: (True, True),
        }[self.level]
        if (self.org_id is not None, self.workspace_id is not None) != expected:
            msg = f"{self.level} target has inconsistent tenant identifiers"
            raise ValueError(msg)
        return self

    @classmethod
    def instance(cls) -> Self:
        return cls(level=Boundary.instance)

    @classmethod
    def org(cls, org_id: UUID) -> Self:
        return cls(level=Boundary.org, org_id=org_id)

    @classmethod
    def workspace(cls, org_id: UUID, workspace_id: UUID) -> Self:
        return cls(level=Boundary.workspace, org_id=org_id, workspace_id=workspace_id)


class Authority(BaseModel):
    model_config = ConfigDict(frozen=True)

    credential_id: UUID
    principal_id: UUID
    credential_kind: str
    boundary: Boundary | None = None
    org_id: UUID | None = None
    workspace_id: UUID | None = None
    permission_ceiling: frozenset[Permission] = frozenset()

    @model_validator(mode="after")
    def valid_boundary(self) -> Self:
        if self.boundary is None:
            if self.org_id is not None or self.workspace_id is not None:
                msg = "a session authority cannot carry a key boundary"
                raise ValueError(msg)
            return self
        Target(level=self.boundary, org_id=self.org_id, workspace_id=self.workspace_id)
        return self

    async def allows(self, permission: Permission, target: Target) -> bool:
        if permission not in self.permission_ceiling:
            return False
        if self.boundary is not None and not self.boundary.covers(self.org_id, self.workspace_id, target):
            return False
        return permission in await principal_permissions(self.principal_id, target)


async def principal_permissions(principal_id: UUID, target: Target) -> frozenset[Permission]:
    from control_plane.models import OrgMembership, User, WorkspaceMembership  # noqa: PLC0415 models import authority enums

    user = await User.find_by_id(principal_id)
    if user is None:
        return frozenset()
    permissions = INSTANCE_ROLE_PERMISSIONS.get(InstanceRole(user.instance_role)) if user.instance_role else None
    granted = permissions or frozenset()
    if target.org_id is not None:
        membership = await OrgMembership.get((principal_id, target.org_id))
        if membership is not None:
            granted |= ORG_ROLE_PERMISSIONS[OrgRole(membership.role)]
    if target.workspace_id is not None:
        membership = await WorkspaceMembership.get((principal_id, target.workspace_id))
        if membership is not None:
            granted |= WORKSPACE_ROLE_PERMISSIONS[WorkspaceRole(membership.role)]
    return granted
