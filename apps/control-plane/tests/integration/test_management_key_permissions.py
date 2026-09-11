from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from helpers import make_org, make_user, make_workspace, run_in_db, setup_control_plane

from control_plane.authz import OrgRole, Permission
from control_plane.models import ManagementKey, OrgMembership, set_actor


@pytest.mark.parametrize("scope", ["instance", "org", "workspace"])
def test_permission_changes_keep_the_token_and_take_effect_on_the_next_request(tmp_path, scope):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        org_headers = cp.headers(org_id)
        workspace_id = make_workspace(client, org_headers)
        path = {
            "instance": "/api/v1/instance/management-keys",
            "org": f"/api/v1/orgs/{org_id}/management-keys",
            "workspace": f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/management-keys",
        }[scope]
        key = client.post(path, json={"label": "editable", "permissions": [Permission.workspaces_read]}, headers=root).json()["data"]
        bearer = {"authorization": f"Bearer {key['token']}"}
        resource = f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}"
        assert client.get(resource, headers=bearer).status_code == 200
        changed = client.put(f"/api/v1/management-keys/{key['id']}/permissions", json={"permissions": [Permission.inference_keys_read]}, headers=root)
        assert changed.status_code == 200, changed.text
        updated = changed.json()["data"]
        assert updated["permissions"] == [Permission.inference_keys_read]
        assert updated["prefix"] == key["prefix"]
        assert updated["parent_id"] == key["parent_id"]
        assert "token" not in updated
        assert "token_hash" not in updated
        assert client.get(resource, headers=bearer).status_code == 403
        assert client.get(f"{resource}/inference-keys", headers=bearer).status_code == 200
        assert (
            client.put(
                f"/api/v1/management-keys/{key['id']}/permissions", json={"permissions": [Permission.workspaces_read]}, headers=root
            ).status_code
            == 200
        )
        assert client.get(resource, headers=bearer).status_code == 200


@pytest.mark.parametrize("permissions", [None, [], ["invalid"], ["workspaces.read", "workspaces.read"]])
def test_permission_changes_reject_invalid_sets(tmp_path, permissions):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        key = client.post(
            "/api/v1/instance/management-keys", json={"label": "editable", "permissions": [Permission.workspaces_read]}, headers=root
        ).json()["data"]
        response = client.put(f"/api/v1/management-keys/{key['id']}/permissions", json={"permissions": permissions}, headers=root)
        assert response.status_code == 422


def test_permission_changes_cannot_exceed_actor_or_parent_or_cross_scope(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        issuer = cp.headers(org_id, permissions=[Permission.management_keys_issue, Permission.workspaces_read, Permission.inference_keys_read])
        key = client.post(
            f"/api/v1/orgs/{org_id}/management-keys", json={"label": "child", "permissions": [Permission.workspaces_read]}, headers=issuer
        ).json()["data"]
        path = f"/api/v1/management-keys/{key['id']}/permissions"
        assert client.put(path, json={"permissions": [Permission.principals_read]}, headers=issuer).status_code == 403
        assert client.put(path, json={"permissions": [Permission.principals_read]}, headers=root).status_code == 403
        assert client.put(path, json={"permissions": [Permission.management_keys_issue]}, headers=root).status_code == 403
        reader = cp.headers(org_id, permissions=[Permission.management_keys_read])
        assert client.put(path, json={"permissions": [Permission.workspaces_read]}, headers=reader).status_code == 403
        other_org = make_org(client, root, "other")
        assert client.put(path, json={"permissions": [Permission.workspaces_read]}, headers=cp.headers(other_org)).status_code == 403
        assert client.put(path, json={"permissions": [Permission.inference_keys_read]}, headers=issuer).status_code == 200


@pytest.mark.parametrize("status", ["expired", "revoked"])
def test_inactive_keys_cannot_be_edited(tmp_path, status):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        key = client.post(
            "/api/v1/instance/management-keys", json={"label": "inactive", "permissions": [Permission.workspaces_read]}, headers=root
        ).json()["data"]

        async def deactivate():
            stored = await ManagementKey.find_by_id(key["id"])
            assert stored is not None
            await set_actor(stored.user_id)
            if status == "expired":
                stored.expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
            else:
                stored.revoked_at = datetime.now(tz=UTC)
            await stored.save()

        run_in_db(tmp_path, deactivate)
        assert (
            client.put(
                f"/api/v1/management-keys/{key['id']}/permissions", json={"permissions": [Permission.inference_keys_read]}, headers=root
            ).status_code
            == 409
        )


def test_reducing_parent_permissions_limits_existing_child_tokens(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        issuer = cp.headers(org_id)
        child = client.post(
            f"/api/v1/orgs/{org_id}/management-keys", json={"label": "child", "permissions": [Permission.workspaces_read]}, headers=issuer
        ).json()["data"]
        bearer = {"authorization": f"Bearer {child['token']}"}
        path = f"/api/v1/orgs/{org_id}/workspaces"
        assert client.get(path, headers=bearer).status_code == 200
        response = client.put(
            f"/api/v1/management-keys/{child['parent_id']}/permissions", json={"permissions": [Permission.inference_keys_read]}, headers=root
        )
        assert response.status_code == 200, response.text
        assert client.get(path, headers=bearer).status_code == 403


def test_permission_changes_cannot_exceed_the_key_principals_current_role(tmp_path):
    cp = setup_control_plane(tmp_path)
    member = make_user(tmp_path, "member@example.com")
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)

        async def join():
            await set_actor(member.id)
            await OrgMembership(user_id=member.id, org_id=org_id, role=OrgRole.member).save()

        run_in_db(tmp_path, join)
        key = client.post(
            f"/api/v1/orgs/{org_id}/management-keys",
            json={"label": "member", "user_id": str(member.id), "permissions": [Permission.organizations_read]},
            headers=root,
        ).json()["data"]
        response = client.put(f"/api/v1/management-keys/{key['id']}/permissions", json={"permissions": [Permission.members_manage]}, headers=root)
        assert response.status_code == 403
        assert "target principal" in response.json()["detail"]
        bearer = {"authorization": f"Bearer {key['token']}"}
        assert client.get(f"/api/v1/orgs/{org_id}", headers=bearer).status_code == 200


def test_permission_updates_reject_other_fields_and_missing_permissions(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        key = client.post(
            "/api/v1/instance/management-keys", json={"label": "unchanged", "permissions": [Permission.workspaces_read]}, headers=root
        ).json()["data"]
        for body in (
            {},
            {"permissions": [Permission.workspaces_read], "parent_id": None},
            {"permissions": [Permission.workspaces_read], "label": "new"},
        ):
            assert client.put(f"/api/v1/management-keys/{key['id']}/permissions", json=body, headers=root).status_code == 422


def test_bearer_cannot_expand_a_key_outside_its_delegation_chain(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        target_headers = cp.headers(org_id, permissions=[Permission.workspaces_read])
        keys = client.get(f"/api/v1/orgs/{org_id}/management-keys", headers=root).json()["data"]
        target = next(key for key in keys if key["permissions"] == [Permission.workspaces_read])
        editor = cp.headers(org_id, permissions=[Permission.management_keys_issue, Permission.workspaces_read, Permission.inference_keys_read])
        response = client.put(
            f"/api/v1/management-keys/{target['id']}/permissions", json={"permissions": [Permission.inference_keys_read]}, headers=editor
        )
        assert response.status_code == 403
        assert client.get(f"/api/v1/orgs/{org_id}/workspaces", headers=target_headers).status_code == 200
