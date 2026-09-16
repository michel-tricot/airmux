from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from helpers import make_org, make_user, make_workspace, setup_control_plane

from contract import uuid7
from control_plane.authz import Permission


def test_access_markers_match_reality(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.post("/api/v1/auth/logout").status_code == 401
        assert client.post("/api/v1/auth/password", json={"current_password": "x", "new_password": "password123"}).status_code == 401


def test_permission_ceiling_restricts_actions_within_a_scope(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers())
        workspace_id = make_workspace(client, cp.headers(org_id))
        reader = cp.headers(org_id, permissions=[Permission.workspaces_read, Permission.inference_keys_read])
        assert client.get(f"/api/v1/organizations/{org_id}/workspaces", headers=reader).status_code == 200
        assert client.post(f"/api/v1/organizations/{org_id}/workspaces", json={"name": "blocked"}, headers=reader).status_code == 403
        assert client.get(f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys", headers=reader).status_code == 200
        assert (
            client.post(
                f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys", json={"label": "blocked"}, headers=reader
            ).status_code
            == 403
        )


def test_org_scope_cannot_reach_instance_or_another_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        first = make_org(client, root, "first")
        second = make_org(client, root, "second")
        key = cp.headers(first)
        assert client.get(f"/api/v1/organizations/{first}/workspaces", headers=key).status_code == 200
        assert client.get("/api/v1/users", headers=key).status_code == 403
        assert client.get(f"/api/v1/organizations/{first}", headers=key).status_code == 200
        assert client.get(f"/api/v1/organizations/{second}", headers=key).status_code == 403


def test_workspace_scope_cannot_reach_its_org_or_sibling(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers())
        org = cp.headers(org_id)
        first = make_workspace(client, org, "first")
        second = make_workspace(client, org, "second")
        key = cp.headers(org_id, workspace_id=first)
        assert client.get(f"/api/v1/organizations/{org_id}/workspaces/{first}", headers=key).status_code == 200
        assert client.get(f"/api/v1/organizations/{org_id}/workspaces/{second}", headers=key).status_code == 403
        assert client.get(f"/api/v1/organizations/{org_id}/workspaces", headers=key).status_code == 403


def test_workspace_usage_reader_sees_only_that_workspace(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        org = cp.headers(org_id)
        first = make_workspace(client, org, "first")
        second = make_workspace(client, org, "second")
        viewer = make_user(tmp_path, "viewer@example.com")
        assert client.put(f"/api/v1/organizations/{org_id}/users/{viewer.id}", json={"role": "member"}, headers=org).status_code == 200
        assert (
            client.put(f"/api/v1/organizations/{org_id}/workspaces/{first}/members/{viewer.id}", json={"role": "viewer"}, headers=org).status_code
            == 200
        )
        key = cp.headers_for(org_id, viewer.id, first, permissions=frozenset({Permission.usage_read}))
        events = [
            {
                "event_id": str(uuid7()),
                "request_id": str(uuid7()),
                "occurred_at": datetime.now(tz=UTC).isoformat(),
                "org_id": str(org_id),
                "workspace_id": str(workspace_id),
                "key_id": "key",
                "model_id": "model",
                "provider_id": "provider",
                "bundle_id": str(uuid4()),
                "input_tokens": 1,
                "output_tokens": 1,
                "cost_usd": "0",
                "latency_ms": 1,
                "status": "ok",
                "stream": False,
                "credential_id": str(uuid7()),
                "credential_scope": "workspace",
            }
            for workspace_id in (first, second)
        ]
        assert client.post("/api/v1/events", json=events, headers=root).status_code == 200

        visible = client.get(f"/api/v1/organizations/{org_id}/workspaces/{first}/events", headers=key)
        assert visible.status_code == 200, visible.text
        assert {event["workspace_id"] for event in visible.json()["data"]} == {str(first)}
        assert client.get(f"/api/v1/organizations/{org_id}/workspaces/{second}/events", headers=key).status_code == 403
