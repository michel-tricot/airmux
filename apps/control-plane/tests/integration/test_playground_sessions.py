from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, setup_control_plane

from contract import BundleV1
from control_plane.authz import Permission


def test_playground_session_is_cookie_only_short_lived_and_reused(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app, base_url="https://testserver") as client:
        org_id = make_org(client, root)
        org = cp.headers(org_id)
        workspace_id = make_workspace(client, org)
        path = f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/playground-session"

        first = client.put(path, headers=org)
        assert first.status_code == 200, first.text
        session = first.json()["data"]
        assert set(session) == {"id", "expires_at", "status"}
        assert session["status"] == "ready"
        expires_at = datetime.fromisoformat(session["expires_at"])
        assert datetime.now(tz=UTC) + timedelta(minutes=4) < expires_at <= datetime.now(tz=UTC) + timedelta(minutes=5)
        cookie = first.headers["set-cookie"]
        assert "airmux_playground=" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie
        assert "Secure" in cookie

        second = client.put(path, headers=org)
        assert second.status_code == 200
        assert second.json()["data"] == session
        assert "set-cookie" not in second.headers

        assert client.get(f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys", headers=org).json()["data"] == []
        bundle = BundleV1.model_validate(client.get("/api/v1/bundle/latest", headers=org).json()["data"])
        assert len(bundle.keys) == 1
        assert bundle.keys[0].key_id == session["id"]
        assert bundle.keys[0].expires_at == expires_at


def test_ending_a_playground_session_clears_the_cookie_and_bundle_entry(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app, base_url="https://testserver") as client:
        org_id = make_org(client, root)
        org = cp.headers(org_id)
        workspace_id = make_workspace(client, org)
        path = f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/playground-session"
        assert client.put(path, headers=org).status_code == 200

        ended = client.delete(path, headers=org)
        assert ended.status_code == 200
        assert ended.json()["data"] == {"status": "ended"}
        assert 'airmux_playground=""' in ended.headers["set-cookie"]
        bundle = BundleV1.model_validate(client.get("/api/v1/bundle/latest", headers=org).json()["data"])
        assert bundle.keys == []


def test_playground_session_requires_execute_permission(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root)
        org = cp.headers(org_id)
        workspace_id = make_workspace(client, org)
        path = f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/playground-session"
        reader = cp.headers(org_id, permissions=[Permission.catalog_read])

        assert client.put(path, headers=reader).status_code == 403
