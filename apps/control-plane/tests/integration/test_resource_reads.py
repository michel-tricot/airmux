from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import make_org, make_user, make_workspace, setup_control_plane

from contract import uuid7


def test_get_org_by_id(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")

        fetched = c.get(f"/api/v1/organizations/{org}", headers=root)
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["data"] == next(o for o in c.get("/api/v1/organizations", headers=root).json()["data"] if o["id"] == str(org))
        assert c.get(f"/api/v1/organizations/{uuid7()}", headers=root).status_code == 404


def test_get_user_by_id_carries_their_memberships(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        user = make_user(tmp_path, "one@example.com")

        c.put(f"/api/v1/organizations/{org}/users/{user.id}", json={"role": "member"}, headers=cp.headers(org))

        fetched = c.get(f"/api/v1/users/{user.id}", headers=root)
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["data"]["org_count"] == 1
        memberships = c.get(f"/api/v1/users/{user.id}/organizations", headers=root).json()["data"]
        assert [membership["org_id"] for membership in memberships] == [str(org)]
        assert c.get(f"/api/v1/users/{uuid7()}", headers=root).status_code == 404


def test_get_workspace_by_id_stays_inside_the_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        other = make_org(c, root, "o2")
        workspace = make_workspace(c, cp.headers(org), "staging")

        fetched = c.get(f"/api/v1/organizations/{org}/workspaces/{workspace}", headers=cp.headers(org))
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["data"]["name"] == "staging"

        assert c.get(f"/api/v1/organizations/{other}/workspaces/{workspace}", headers=cp.headers(other)).status_code == 404
        assert c.get(f"/api/v1/organizations/{org}/workspaces/{uuid7()}", headers=cp.headers(org)).status_code == 404
