from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, setup_control_plane

from control_plane.authz import ORG_ROLE_PERMISSIONS, WORKSPACE_ROLE_PERMISSIONS, OrgRole, Permission, WorkspaceRole

CSRF = {"X-Requested-With": "fetch"}


PASSWORD = "hunter2-hunter2"


def _client(cp) -> TestClient:
    return TestClient(cp.app, base_url="https://testserver")


def _signup(c, email: str) -> str:
    me = c.post("/api/v1/auth/signup", json={"email": email, "name": email, "password": PASSWORD}).json()["data"]
    return me["user_id"]


def test_session_user_sees_org_role_permissions(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        org_id = make_org(c, root, "o1")
        user_id = _signup(c, "member@example.com")
        assert c.put(f"/api/v1/orgs/{org_id}/users/{user_id}", json={"role": "member"}, headers=cp.headers(org_id)).status_code == 200

        resp = c.get(f"/api/v1/auth/permissions?org_id={org_id}", headers=CSRF)
        assert resp.status_code == 200
        assert set(resp.json()["data"]["permissions"]) == {p.value for p in ORG_ROLE_PERMISSIONS[OrgRole.member]}

        resp = c.get("/api/v1/auth/permissions", headers=CSRF)
        assert resp.status_code == 200
        assert resp.json()["data"]["permissions"] == []


def test_session_user_sees_effective_workspace_permissions(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        org_id = make_org(c, root, "o1")
        workspace_id = make_workspace(c, cp.headers(org_id), "staging")
        user_id = _signup(c, "viewer@example.com")
        assert c.put(f"/api/v1/orgs/{org_id}/users/{user_id}", json={"role": "member"}, headers=cp.headers(org_id)).status_code == 200
        assert (
            c.put(
                f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/members/{user_id}",
                json={"role": "viewer"},
                headers=cp.headers(org_id),
            ).status_code
            == 200
        )

        resp = c.get(f"/api/v1/auth/permissions?org_id={org_id}&workspace_ref={workspace_id}", headers=CSRF)
        assert resp.status_code == 200
        expected = ORG_ROLE_PERMISSIONS[OrgRole.member] | WORKSPACE_ROLE_PERMISSIONS[WorkspaceRole.viewer]
        assert set(resp.json()["data"]["permissions"]) == {permission.value for permission in expected}


def test_workspace_permission_scope_requires_an_org_and_existing_workspace(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        org_id = make_org(c, root, "o1")
        assert c.get("/api/v1/auth/permissions?workspace_ref=staging", headers=root).status_code == 422
        assert c.get(f"/api/v1/auth/permissions?org_id={org_id}&workspace_ref=missing", headers=root).status_code == 404


def test_org_key_cannot_read_instance_or_other_org_permissions(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        org_a = make_org(c, root, "oa")
        org_b = make_org(c, root, "ob")
        org_headers = cp.headers(org_a)

        resp = c.get(f"/api/v1/auth/permissions?org_id={org_a}", headers=org_headers)
        assert resp.status_code == 200
        assert Permission.management_keys_issue.value in resp.json()["data"]["permissions"]

        limited = c.get(
            f"/api/v1/auth/permissions?org_id={org_a}",
            headers=cp.headers(org_a, permissions=[Permission.workspaces_read]),
        )
        assert limited.status_code == 200
        assert limited.json()["data"]["permissions"] == [Permission.workspaces_read]

        resp = c.get("/api/v1/auth/permissions", headers=org_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["permissions"] == []

        resp = c.get(f"/api/v1/auth/permissions?org_id={org_b}", headers=org_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["permissions"] == []


def test_unknown_org_returns_404_and_anonymous_401(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        resp = c.get(f"/api/v1/auth/permissions?org_id={uuid4()}", headers=root)
        assert resp.status_code == 404

        resp = c.get("/api/v1/auth/permissions", headers=CSRF)
        assert resp.status_code == 401


def test_service_account_management_key_sees_its_effective_permissions(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        service_account = c.post(
            "/api/v1/service-accounts",
            json={"name": "automation", "instance_role": "auditor"},
            headers=root,
        ).json()["data"]
        key = c.post(
            "/api/v1/instance/management-keys",
            json={
                "label": "automation",
                "user_id": service_account["id"],
                "permissions": [Permission.organizations_read],
            },
            headers=root,
        ).json()["data"]

        resp = c.get("/api/v1/auth/permissions", headers={"authorization": f"Bearer {key['token']}"})
        assert resp.status_code == 200
        assert resp.json()["data"]["permissions"] == [Permission.organizations_read]
