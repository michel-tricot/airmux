from __future__ import annotations

from datetime import UTC, datetime, timedelta

from helpers import run_in_db, setup_db

from contract import token_hash
from control_plane.authority import is_allowed
from control_plane.authz import (
    OrgRole,
    Permission,
    Scope,
)
from control_plane.keys import MANAGEMENT_KEY_PREFIX, ManagementKeyGrant, mint_management_key, verify_management_key
from control_plane.models import ManagementKey, Org, OrgMembership, User, Workspace, WorkspaceMembership, set_actor


def test_management_key_has_one_prefix_explicit_permissions_and_a_stored_hash(tmp_path):
    setup_db(tmp_path)

    async def flow():
        user = User(email="owner@example.com", name="Owner", instance_role="owner")
        await set_actor(user.id)
        await user.save()
        key_id, token = await mint_management_key(
            ManagementKeyGrant(
                principal_id=user.id,
                scope=Scope.instance(),
                permissions=frozenset({Permission.organizations_read}),
                label="test",
            )
        )
        return token, await ManagementKey.find_by_id(key_id), await verify_management_key(token)

    token, key, authority = run_in_db(tmp_path, flow)
    assert token.startswith(MANAGEMENT_KEY_PREFIX)
    assert key is not None
    assert key.permissions == [Permission.organizations_read]
    assert key.token_hash == token_hash(token)
    assert token not in key.model_dump_json()
    assert authority is not None
    assert authority.grant.permissions == frozenset({Permission.organizations_read})


def test_role_loss_removes_authority_without_changing_the_key(tmp_path):
    setup_db(tmp_path)

    async def flow():
        owner = User(email="owner@example.com", name="Owner")
        await set_actor(owner.id)
        await owner.save()
        org = await Org.create("Org")
        membership = await OrgMembership(user_id=owner.id, org_id=org.id, role=OrgRole.owner).save()
        workspace = await Workspace(org_id=org.id, name="Workspace", slug="workspace").save()
        await WorkspaceMembership(user_id=owner.id, workspace_id=workspace.id, org_id=org.id, role="admin").save()
        _, token = await mint_management_key(
            ManagementKeyGrant(
                principal_id=owner.id,
                scope=Scope.org(org.id),
                permissions=frozenset({Permission.workspaces_read, Permission.inference_keys_manage}),
                label="test",
            )
        )
        authority = await verify_management_key(token)
        assert authority is not None
        before = await is_allowed(authority, Permission.inference_keys_manage, Scope.workspace(org.id, workspace.id))
        membership.role = OrgRole.member
        await membership.save()
        workspace_membership = await WorkspaceMembership.get((owner.id, workspace.id))
        assert workspace_membership is not None
        workspace_membership.role = "viewer"
        await workspace_membership.save()
        after = await is_allowed(authority, Permission.inference_keys_manage, Scope.workspace(org.id, workspace.id))
        stored = await ManagementKey.find_by_id(authority.credential_id)
        return before, after, stored.permissions if stored else None

    before, after, permissions = run_in_db(tmp_path, flow)
    assert before
    assert not after
    assert permissions == [Permission.inference_keys_manage, Permission.workspaces_read]


def test_expired_management_key_is_rejected(tmp_path):
    setup_db(tmp_path)

    async def flow():
        user = User(email="owner@example.com", name="Owner", instance_role="owner")
        await set_actor(user.id)
        await user.save()
        _, token = await mint_management_key(
            ManagementKeyGrant(
                principal_id=user.id,
                scope=Scope.instance(),
                permissions=frozenset({Permission.organizations_read}),
                label="expired",
                expires_at=datetime.now(tz=UTC) - timedelta(seconds=1),
            )
        )
        return await verify_management_key(token)

    assert run_in_db(tmp_path, flow) is None
