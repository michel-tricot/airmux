from __future__ import annotations

from contract import uuid7
from control_plane.authz import (
    DATA_PLANE_PERMISSIONS,
    INSTANCE_ROLE_PERMISSIONS,
    AccessRequest,
    Actor,
    Decision,
    Grant,
    InstanceRole,
    OrgRole,
    Permission,
    Scope,
    decide,
    permissions_for_org_role,
)


def test_data_plane_role_has_only_its_runtime_permissions():
    assert (
        frozenset(
            {
                Permission.bundles_read,
                Permission.usage_ingest,
                Permission.data_planes_heartbeat,
            }
        )
        == DATA_PLANE_PERMISSIONS
    )
    assert INSTANCE_ROLE_PERMISSIONS[InstanceRole.data_plane] == DATA_PLANE_PERMISSIONS
    assert permissions_for_org_role(OrgRole.data_plane) == DATA_PLANE_PERMISSIONS
    assert Permission.data_planes_read not in permissions_for_org_role(OrgRole.owner)
    assert Permission.data_planes_read not in permissions_for_org_role(OrgRole.admin)


def test_key_scopes_reach_only_their_descendants():
    org_id = uuid7()
    other_org_id = uuid7()
    workspace_id = uuid7()
    other_workspace_id = uuid7()
    instance = Scope.instance()
    org = Scope.org(org_id)
    other_org = Scope.org(other_org_id)
    workspace = Scope.workspace(org_id, workspace_id)
    sibling = Scope.workspace(org_id, other_workspace_id)

    assert instance.covers(instance)
    assert instance.covers(org)
    assert instance.covers(workspace)
    assert org.covers(org)
    assert org.covers(workspace)
    assert not org.covers(instance)
    assert not org.covers(other_org)
    assert workspace.covers(workspace)
    assert not workspace.covers(org)
    assert not workspace.covers(sibling)


def test_decision_requires_credential_scope_ceiling_and_standing_grant():
    org_id = uuid7()
    other_org_id = uuid7()
    permission = Permission.workspaces_read
    actor = Actor(
        credential_id=uuid7(),
        principal_id=uuid7(),
        credential_kind="management_key",
        grant=Grant(scope=Scope.org(org_id), permissions=frozenset({permission})),
    )
    standing = (Grant(scope=Scope.org(org_id), permissions=frozenset({permission})),)

    assert decide(actor, standing, AccessRequest(permission=permission, target=Scope.org(org_id))) is Decision.allow
    assert decide(actor, standing, AccessRequest(permission=permission, target=Scope.org(other_org_id))) is Decision.credential_scope
    without_ceiling = actor.model_copy(update={"grant": Grant(scope=Scope.org(org_id), permissions=frozenset())})
    assert decide(without_ceiling, standing, AccessRequest(permission=permission, target=Scope.org(org_id))) is Decision.credential_ceiling
    assert decide(actor, (), AccessRequest(permission=permission, target=Scope.org(org_id))) is Decision.standing_authority


def test_actor_throttle_identity_follows_the_credential_kind():
    principal_id = uuid7()
    credential_id = uuid7()
    actor = Actor(
        credential_id=credential_id,
        principal_id=principal_id,
        credential_kind="management_key",
        grant=Grant(scope=Scope.instance(), permissions=frozenset()),
    )

    assert actor.throttle_identity == credential_id
    assert actor.model_copy(update={"credential_kind": "session"}).throttle_identity == principal_id
