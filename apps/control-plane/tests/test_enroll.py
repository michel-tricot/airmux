from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import make_org, setup_control_plane

CSRF = {"X-Requested-With": "fetch"}
PASSWORD = "hunter2-hunter2"


def _client(cp) -> TestClient:
    return TestClient(cp.app, base_url="https://testserver")


def _signup(c, email="m@example.com"):
    resp = c.post("/v1/auth/signup", json={"email": email, "name": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_personal_org_is_born_with_its_creator_as_member(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        me = _signup(c)
        assert c.get("/v1/enroll", headers=CSRF).json()["data"] == {"orgs": [], "personal_org_id": None}

        created = c.post("/v1/enroll/org", json={"name": "michels"}, headers=CSRF)
        assert created.status_code == 200, created.text
        org = created.json()["data"]
        assert org["personal_for"] == me["user_id"]

        standing = c.get("/v1/enroll", headers=CSRF).json()["data"]
        assert [o["id"] for o in standing["orgs"]] == [org["id"]]
        assert standing["personal_org_id"] == org["id"]
        assert c.get("/v1/auth/me", headers=CSRF).json()["data"]["orgs"] == [org["id"]]
        assert c.get("/v1/org/workspaces", headers={**CSRF, "X-Org-Id": org["id"]}).status_code == 200


def test_personal_org_is_capped_at_one_per_user(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        _signup(c)
        assert c.post("/v1/enroll/org", json={"name": "first"}, headers=CSRF).status_code == 200
        again = c.post("/v1/enroll/org", json={"name": "second"}, headers=CSRF)
        assert again.status_code == 409
        assert len(c.get("/v1/enroll", headers=CSRF).json()["data"]["orgs"]) == 1


def test_enrollment_lists_granted_orgs_but_only_marks_the_personal_one(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        granted = make_org(c, root, "granted")
        me = _signup(c)
        assert c.put(f"/v1/users/{me['user_id']}/orgs/{granted}", headers=root).status_code == 200
        personal = c.post("/v1/enroll/org", json={"name": "mine"}, headers=CSRF).json()["data"]

        standing = c.get("/v1/enroll", headers=CSRF).json()["data"]
        assert {o["id"] for o in standing["orgs"]} == {str(granted), personal["id"]}
        assert standing["personal_org_id"] == personal["id"]


def test_enrollment_works_through_the_bearer_door_too(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        created = c.post("/v1/enroll/org", json={"name": "admins-own"}, headers=root)
        assert created.status_code == 200, created.text
        assert c.post("/v1/enroll/org", json={"name": "again"}, headers=root).status_code == 409
        standing = c.get("/v1/enroll", headers=root).json()["data"]
        assert standing["personal_org_id"] == created.json()["data"]["id"]


def test_admin_provisioned_orgs_are_not_personal(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        make_org(c, root, "provisioned")
        listed = c.get("/v1/orgs", headers=root).json()["data"]
        assert [o["personal_for"] for o in listed] == [None]


def test_personal_slot_survives_membership_removal(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        me = _signup(c)
        org = c.post("/v1/enroll/org", json={"name": "mine"}, headers=CSRF).json()["data"]
        assert c.delete(f"/v1/users/{me['user_id']}/orgs/{org['id']}", headers=root).status_code == 200

        standing = c.get("/v1/enroll", headers=CSRF).json()["data"]
        assert standing["orgs"] == []
        assert standing["personal_org_id"] == org["id"]
        assert c.post("/v1/enroll/org", json={"name": "second"}, headers=CSRF).status_code == 409
