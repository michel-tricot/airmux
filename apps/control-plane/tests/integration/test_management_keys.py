from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from helpers import make_org, make_user, make_workspace, run_in_db, setup_control_plane

from control_plane.authz import Permission
from control_plane.keys import MANAGEMENT_KEY_PREFIX
from control_plane.models import ManagementKey, set_actor


@pytest.mark.parametrize("scope", ["instance", "org", "workspace"])
def test_management_key_issuance_rejects_a_target_principal(tmp_path, scope):
    cp = setup_control_plane(tmp_path)
    target = make_user(tmp_path, "target@example.com")
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        workspace_id = make_workspace(client, cp.headers(org_id))
        path = (
            "/api/v1/instance/management-keys"
            if scope == "instance"
            else f"/api/v1/organizations/{org_id}/management-keys"
            if scope == "org"
            else f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/management-keys"
        )
        response = client.post(
            path,
            headers=root,
            json={
                "label": "impersonation",
                "permissions": [Permission.workspaces_read],
                "user_id": str(target.id),
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"][0]["type"] == "extra_forbidden"


def test_admin_cannot_impersonate_owner_and_descendant_loses_authority_after_demotion(tmp_path):
    cp = setup_control_plane(tmp_path)
    admin = make_user(tmp_path, "admin@example.com")
    owner = make_user(tmp_path, "owner@example.com")
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        for user, role in ((admin, "admin"), (owner, "owner")):
            assert client.put(f"/api/v1/organizations/{org_id}/users/{user.id}", headers=root, json={"role": role}).status_code == 200
        issuer = cp.headers_for(org_id, admin.id)
        path = f"/api/v1/organizations/{org_id}/management-keys"
        payload = {"label": "delegated", "permissions": [Permission.members_manage]}
        assert client.post(path, headers=issuer, json={**payload, "user_id": str(owner.id)}).status_code == 422
        response = client.post(path, headers=issuer, json=payload)
        assert response.status_code == 200, response.text
        key = response.json()["data"]
        assert key["user_id"] == str(admin.id)
        bearer = {"authorization": f"Bearer {key['token']}"}
        member_path = f"/api/v1/organizations/{org_id}/users/{admin.id}"
        assert client.put(member_path, headers=bearer, json={"role": "owner"}).status_code == 403
        assert client.put(member_path, headers=root, json={"role": "member"}).status_code == 200
        assert client.put(member_path, headers=bearer, json={"role": "admin"}).status_code == 403
        assert client.delete(f"/api/v1/management-keys/{key['parent_id']}", headers=root).status_code == 200
        assert client.put(member_path, headers=bearer, json={"role": "admin"}).status_code == 401


def test_management_key_api_creates_lists_and_revokes_one_resource_type(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        response = client.post(
            f"/api/v1/organizations/{org_id}/management-keys",
            json={"label": "ci", "permissions": [Permission.workspaces_read]},
            headers=root,
        )
        assert response.status_code == 200, response.text
        key = response.json()["data"]
        assert key["token"].startswith(MANAGEMENT_KEY_PREFIX)
        assert key["scope"] == {"level": "org", "org_id": str(org_id), "workspace_id": None}
        assert key["org_id"] == str(org_id)
        assert key["workspace_id"] is None
        assert key["permissions"] == [Permission.workspaces_read]
        assert key["status"] == "active"

        listed = client.get(f"/api/v1/organizations/{org_id}/management-keys", headers=root)
        assert listed.status_code == 200, listed.text
        stored = next(candidate for candidate in listed.json()["data"] if candidate["id"] == key["id"])
        assert stored["prefix"] == key["token"][:12]
        assert "token" not in stored
        assert "token_hash" not in stored

        child_headers = {"authorization": f"Bearer {key['token']}"}
        assert client.get(f"/api/v1/organizations/{org_id}/workspaces", headers=child_headers).status_code == 200
        assert client.get("/api/v1/users", headers=child_headers).status_code == 403

        revoked = client.delete(f"/api/v1/management-keys/{key['id']}", headers=root)
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["data"]["status"] == "revoked"
        assert client.get(f"/api/v1/organizations/{org_id}/workspaces", headers=child_headers).status_code == 401
        relisted = client.get(f"/api/v1/organizations/{org_id}/management-keys", headers=root).json()["data"]
        assert next(candidate for candidate in relisted if candidate["id"] == key["id"])["status"] == "revoked"


def test_management_key_permissions_are_required_and_validated(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        headers = cp.headers()
        assert client.post("/api/v1/instance/management-keys", json={"label": "missing"}, headers=headers).status_code == 422
        assert client.post("/api/v1/instance/management-keys", json={"label": "empty", "permissions": []}, headers=headers).status_code == 422
        assert (
            client.post(
                "/api/v1/instance/management-keys", json={"label": "unknown", "permissions": ["future.permission"]}, headers=headers
            ).status_code
            == 422
        )
        naive_expiry = client.post(
            "/api/v1/instance/management-keys",
            json={"label": "naive", "permissions": [Permission.organizations_read], "expires_at": "2030-01-01T00:00:00"},
            headers=headers,
        )
        assert naive_expiry.status_code == 422


def test_bearer_delegation_is_strictly_attenuated_and_cannot_redelegate(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        cannot_delegate = client.post(
            f"/api/v1/organizations/{org_id}/management-keys",
            json={
                "label": "peer",
                "permissions": [Permission.management_keys_issue, Permission.workspaces_read],
            },
            headers=root,
        )
        assert cannot_delegate.status_code == 403

        issuer = cp.headers(org_id)
        child = client.post(
            f"/api/v1/organizations/{org_id}/management-keys",
            json={"label": "child", "permissions": [Permission.workspaces_read]},
            headers=issuer,
        ).json()["data"]
        assert child["parent_id"] is not None
        assert child["org_id"] == str(org_id)
        child_headers = {"authorization": f"Bearer {child['token']}"}
        assert (
            client.post(
                f"/api/v1/organizations/{org_id}/management-keys",
                json={"label": "grandchild", "permissions": [Permission.workspaces_read]},
                headers=child_headers,
            ).status_code
            == 403
        )

        assert client.delete(f"/api/v1/management-keys/{child['parent_id']}", headers=root).status_code == 200
        assert client.get(f"/api/v1/organizations/{org_id}/workspaces", headers=child_headers).status_code == 401


def test_expired_management_key_is_reported_as_expired(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        management_key = client.post(
            "/api/v1/instance/management-keys",
            json={
                "label": "short-lived",
                "permissions": [Permission.organizations_read],
                "expires_at": (datetime.now(tz=UTC) + timedelta(hours=1)).isoformat(),
            },
            headers=root,
        ).json()["data"]

        async def expire():
            key = await ManagementKey.find_by_id(management_key["id"])
            assert key is not None
            await set_actor(key.user_id)
            key.expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
            await key.save()

        run_in_db(tmp_path, expire)
        keys = client.get("/api/v1/instance/management-keys", headers=root).json()["data"]
        assert next(key for key in keys if key["id"] == management_key["id"])["status"] == "expired"
