from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from helpers import make_org, run_in_db, setup_control_plane

from control_plane.authz import Permission
from control_plane.keys import ACCESS_KEY_PREFIX
from control_plane.models import AccessKey, set_actor


def test_access_key_api_mints_lists_and_revokes_one_resource_type(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        minted = client.post(
            "/v1/access-keys",
            json={"label": "ci", "org_id": str(org_id), "permissions": [Permission.workspaces_read]},
            headers=root,
        )
        assert minted.status_code == 200, minted.text
        key = minted.json()["data"]
        assert key["token"].startswith(ACCESS_KEY_PREFIX)
        assert key["boundary"] == "org"
        assert key["org_id"] == str(org_id)
        assert key["workspace_id"] is None
        assert key["permissions"] == [Permission.workspaces_read]
        assert key["status"] == "active"

        listed = client.get("/v1/access-keys", params={"org_id": str(org_id)}, headers=root)
        assert listed.status_code == 200, listed.text
        stored = next(candidate for candidate in listed.json()["data"] if candidate["id"] == key["id"])
        assert stored["prefix"] == key["token"][:12]
        assert "token" not in stored
        assert "token_hash" not in stored

        child_headers = {"authorization": f"Bearer {key['token']}"}
        assert client.get("/v1/org/workspaces", headers=child_headers).status_code == 200
        assert client.get("/v1/users", headers=child_headers).status_code == 403

        revoked = client.delete(f"/v1/access-keys/{key['id']}", headers=root)
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["data"]["status"] == "revoked"
        assert client.get("/v1/org/workspaces", headers=child_headers).status_code == 401
        relisted = client.get("/v1/access-keys", params={"org_id": str(org_id)}, headers=root).json()["data"]
        assert next(candidate for candidate in relisted if candidate["id"] == key["id"])["status"] == "revoked"


def test_access_key_permissions_are_required_and_validated(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        headers = cp.headers()
        assert client.post("/v1/access-keys", json={"label": "missing"}, headers=headers).status_code == 422
        assert client.post("/v1/access-keys", json={"label": "empty", "permissions": []}, headers=headers).status_code == 422
        assert client.post("/v1/access-keys", json={"label": "unknown", "permissions": ["future.permission"]}, headers=headers).status_code == 422
        naive_expiry = client.post(
            "/v1/access-keys",
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
            "/v1/access-keys",
            json={
                "label": "peer",
                "org_id": str(org_id),
                "permissions": [Permission.access_keys_issue, Permission.workspaces_read],
            },
            headers=root,
        )
        assert cannot_delegate.status_code == 403

        issuer = cp.headers(org_id)
        child = client.post(
            "/v1/access-keys",
            json={"label": "child", "permissions": [Permission.workspaces_read]},
            headers=issuer,
        ).json()["data"]
        assert child["parent_id"] is not None
        assert child["org_id"] == str(org_id)
        child_headers = {"authorization": f"Bearer {child['token']}"}
        assert (
            client.post(
                "/v1/access-keys",
                json={"label": "grandchild", "org_id": str(org_id), "permissions": [Permission.workspaces_read]},
                headers=child_headers,
            ).status_code
            == 403
        )

        assert client.delete(f"/v1/access-keys/{child['parent_id']}", headers=root).status_code == 200
        assert client.get("/v1/org/workspaces", headers=child_headers).status_code == 401


def test_expired_access_key_is_reported_as_expired(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        minted = client.post(
            "/v1/access-keys",
            json={
                "label": "short-lived",
                "permissions": [Permission.organizations_read],
                "expires_at": (datetime.now(tz=UTC) + timedelta(hours=1)).isoformat(),
            },
            headers=root,
        ).json()["data"]

        async def expire():
            key = await AccessKey.find_by_id(minted["id"])
            assert key is not None
            await set_actor(key.user_id)
            key.expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
            await key.save()

        run_in_db(tmp_path, expire)
        keys = client.get("/v1/access-keys", headers=root).json()["data"]
        assert next(key for key in keys if key["id"] == minted["id"])["status"] == "expired"
