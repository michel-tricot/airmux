from __future__ import annotations

from datetime import UTC, datetime, timedelta

from helpers import run_in_db, setup_db

from contract import token_hash, uuid7
from control_plane.authz import (
    DATA_PLANE_PERMISSIONS,
    Boundary,
    OrgRole,
    Permission,
    Target,
    permissions_for_org_role,
)
from control_plane.keys import ACCESS_KEY_PREFIX, AccessKeyGrant, mint_access_key, verify_access_key
from control_plane.models import AccessKey, Org, OrgMembership, User, Workspace, WorkspaceMembership, set_actor


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
    assert permissions_for_org_role(OrgRole.data_plane) == DATA_PLANE_PERMISSIONS
    assert Permission.data_planes_read not in permissions_for_org_role(OrgRole.owner)
    assert Permission.data_planes_read not in permissions_for_org_role(OrgRole.admin)


def test_key_boundaries_reach_only_their_descendants():
    org_id = uuid7()
    other_org_id = uuid7()
    workspace_id = uuid7()
    other_workspace_id = uuid7()
    instance = Target.instance()
    org = Target.org(org_id)
    other_org = Target.org(other_org_id)
    workspace = Target.workspace(org_id, workspace_id)
    sibling = Target.workspace(org_id, other_workspace_id)

    assert Boundary.instance.covers(None, None, instance)
    assert Boundary.instance.covers(None, None, org)
    assert Boundary.instance.covers(None, None, workspace)
    assert Boundary.org.covers(org_id, None, org)
    assert Boundary.org.covers(org_id, None, workspace)
    assert not Boundary.org.covers(org_id, None, instance)
    assert not Boundary.org.covers(org_id, None, other_org)
    assert Boundary.workspace.covers(org_id, workspace_id, workspace)
    assert not Boundary.workspace.covers(org_id, workspace_id, org)
    assert not Boundary.workspace.covers(org_id, workspace_id, sibling)


def test_access_key_has_one_prefix_explicit_permissions_and_a_stored_hash(tmp_path):
    setup_db(tmp_path)

    async def flow():
        user = User(email="owner@example.com", name="Owner", instance_role="owner")
        await set_actor(user.id)
        await user.save()
        key_id, token = await mint_access_key(
            AccessKeyGrant(
                principal_id=user.id,
                target=Target.instance(),
                permissions=frozenset({Permission.organizations_read}),
                label="test",
            )
        )
        return token, await AccessKey.find_by_id(key_id), await verify_access_key(token)

    token, key, authority = run_in_db(tmp_path, flow)
    assert token.startswith(ACCESS_KEY_PREFIX)
    assert key is not None
    assert key.permissions == [Permission.organizations_read]
    assert key.token_hash == token_hash(token)
    assert token not in key.model_dump_json()
    assert authority is not None
    assert authority.permission_ceiling == frozenset({Permission.organizations_read})


def test_role_loss_removes_authority_without_changing_the_key(tmp_path):
    setup_db(tmp_path)

    async def flow():
        owner = User(email="owner@example.com", name="Owner")
        await set_actor(owner.id)
        await owner.save()
        org = await Org(name="Org").save()
        membership = await OrgMembership(user_id=owner.id, org_id=org.id, role=OrgRole.owner).save()
        workspace = await Workspace(org_id=org.id, name="Workspace", slug="workspace").save()
        await WorkspaceMembership(user_id=owner.id, workspace_id=workspace.id, org_id=org.id, role="admin").save()
        _, token = await mint_access_key(
            AccessKeyGrant(
                principal_id=owner.id,
                target=Target.org(org.id),
                permissions=frozenset({Permission.workspaces_read, Permission.inference_keys_manage}),
                label="test",
            )
        )
        authority = await verify_access_key(token)
        assert authority is not None
        before = await authority.allows(Permission.inference_keys_manage, Target.workspace(org.id, workspace.id))
        membership.role = OrgRole.member
        await membership.save()
        workspace_membership = await WorkspaceMembership.get((owner.id, workspace.id))
        assert workspace_membership is not None
        workspace_membership.role = "viewer"
        await workspace_membership.save()
        after = await authority.allows(Permission.inference_keys_manage, Target.workspace(org.id, workspace.id))
        stored = await AccessKey.find_by_id(authority.credential_id)
        return before, after, stored.permissions if stored else None

    before, after, permissions = run_in_db(tmp_path, flow)
    assert before
    assert not after
    assert permissions == [Permission.inference_keys_manage, Permission.workspaces_read]


def test_expired_access_key_is_rejected(tmp_path):
    setup_db(tmp_path)

    async def flow():
        user = User(email="owner@example.com", name="Owner", instance_role="owner")
        await set_actor(user.id)
        await user.save()
        _, token = await mint_access_key(
            AccessKeyGrant(
                principal_id=user.id,
                target=Target.instance(),
                permissions=frozenset({Permission.organizations_read}),
                label="expired",
                expires_at=datetime.now(tz=UTC) - timedelta(seconds=1),
            )
        )
        return await verify_access_key(token)

    assert run_in_db(tmp_path, flow) is None
