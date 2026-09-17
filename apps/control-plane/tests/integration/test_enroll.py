from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import make_org, make_user, setup_control_plane

CSRF = {"X-Requested-With": "fetch"}


PASSWORD = "hunter2-hunter2"


def _client(cp) -> TestClient:
    return TestClient(cp.app, base_url="https://testserver")


def _signup(c, email="m@example.com"):
    resp = c.post("/api/v1/auth/signup", json={"email": email, "name": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _orgs(c, headers):
    response = c.get("/api/v1/enroll/organizations", headers=headers)
    assert set(response.json()) == {"data"}
    return response.json()["data"]


def test_personal_org_is_born_with_its_creator_as_member(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        me = _signup(c)
        assert c.get("/api/v1/enroll", headers=CSRF).json()["data"] == {
            "personal_org_id": None,
            "org_count": 0,
            "pending_invitation_count": 0,
        }

        created = c.post("/api/v1/enroll/org", json={"name": "michels"}, headers=CSRF)
        assert created.status_code == 200, created.text
        org = created.json()["data"]
        assert org["personal_for"] == me["user_id"]

        standing = c.get("/api/v1/enroll", headers=CSRF).json()["data"]
        assert [organization["id"] for organization in _orgs(c, CSRF)] == [org["id"]]
        assert standing["personal_org_id"] == org["id"]
        assert standing["org_count"] == 1
        assert c.get("/api/v1/auth/me", headers=CSRF).json()["data"]["org_count"] == 1
        assert c.get(f"/api/v1/organizations/{org['id']}/workspaces", headers=CSRF).status_code == 200


def test_personal_org_is_capped_at_one_per_user(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        _signup(c)
        assert c.post("/api/v1/enroll/org", json={"name": "first"}, headers=CSRF).status_code == 200
        again = c.post("/api/v1/enroll/org", json={"name": "second"}, headers=CSRF)
        assert again.status_code == 409
        assert c.get("/api/v1/enroll", headers=CSRF).json()["data"]["org_count"] == 1


def test_enrollment_lists_granted_orgs_but_only_marks_the_personal_one(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        granted = make_org(c, root, "granted")
        me = _signup(c)
        assert (
            c.put(f"/api/v1/organizations/{granted}/users/{me['user_id']}", json={"role": "member"}, headers=cp.headers(granted)).status_code == 200
        )
        personal = c.post("/api/v1/enroll/org", json={"name": "mine"}, headers=CSRF).json()["data"]

        standing = c.get("/api/v1/enroll", headers=CSRF).json()["data"]
        assert {organization["id"] for organization in _orgs(c, CSRF)} == {str(granted), personal["id"]}
        assert standing["org_count"] == 2
        assert standing["personal_org_id"] == personal["id"]


def test_bearer_can_read_enrollment_but_cannot_found_a_personal_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        assert c.post("/api/v1/enroll/org", json={"name": "admins-own"}, headers=root).status_code == 401
        standing = c.get("/api/v1/enroll", headers=root).json()["data"]
        assert standing == {"personal_org_id": None, "org_count": 0, "pending_invitation_count": 0}


def test_org_bound_bearer_does_not_disclose_other_memberships(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        first = make_org(c, root, "first")
        second = make_org(c, root, "second")
        user = make_user(tmp_path, "member@example.com")
        assert c.put(f"/api/v1/organizations/{first}/users/{user.id}", json={"role": "member"}, headers=cp.headers(first)).status_code == 200
        assert c.put(f"/api/v1/organizations/{second}/users/{user.id}", json={"role": "member"}, headers=cp.headers(second)).status_code == 200

        bearer = cp.headers_for(first, user.id)
        standing = c.get("/api/v1/enroll", headers=bearer).json()["data"]
        assert [org["id"] for org in _orgs(c, bearer)] == [str(first)]
        assert standing["org_count"] == 1
        assert standing["personal_org_id"] is None
        assert c.get("/api/v1/auth/me", headers=bearer).json()["data"]["org_count"] == 1


def test_admin_provisioned_orgs_are_not_personal(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        make_org(c, root, "provisioned")
        listed = c.get("/api/v1/organizations", headers=root).json()["data"]
        assert [o["personal_for"] for o in listed] == [None]


def test_personal_slot_survives_membership_removal(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        me = _signup(c)
        org = c.post("/api/v1/enroll/org", json={"name": "mine"}, headers=CSRF).json()["data"]
        successor = make_user(tmp_path, "successor@example.com")
        org_headers = cp.headers(org["id"])
        assert c.put(f"/api/v1/organizations/{org['id']}/users/{successor.id}", json={"role": "owner"}, headers=org_headers).status_code == 200
        assert c.delete(f"/api/v1/organizations/{org['id']}/users/{me['user_id']}", headers=org_headers).status_code == 200

        standing = c.get("/api/v1/enroll", headers=CSRF).json()["data"]
        assert standing["org_count"] == 0
        assert _orgs(c, CSRF) == []
        assert standing["personal_org_id"] == org["id"]
        assert c.post("/api/v1/enroll/org", json={"name": "second"}, headers=CSRF).status_code == 409
