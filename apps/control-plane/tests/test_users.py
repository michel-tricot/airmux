from __future__ import annotations

import re

from fastapi.testclient import TestClient
from helpers import setup_control_plane


def test_user_create_returns_full_resource_with_server_id(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        created = c.post("/instance/users", json={"email": "michel@example.com"}, headers=root).json()
        assert created["id"].startswith("u-")
        assert created["email"] == "michel@example.com"
        assert created["name"] == "michel@example.com"
        assert created["instance_admin"] is False
        assert created["orgs"] == []
        assert c.post("/instance/users", json={"email": "michel@example.com"}, headers=root).status_code == 409


def test_service_account_gets_a_derived_email(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        created = c.post("/instance/service-accounts", json={"name": "Data Plane"}, headers=root).json()
        assert created["service_account"] is True
        assert created["name"] == "Data Plane"
        assert re.fullmatch(r"data-plane-[0-9a-f]{8}@airbytesvcaccount\.ai", created["email"])
        again = c.post("/instance/service-accounts", json={"name": "Data Plane"}, headers=root).json()
        assert again["email"] != created["email"]
        assert c.post("/instance/service-accounts", json={"name": "!!"}, headers=root).status_code == 422


def test_service_account_is_a_full_principal(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)
        created = c.post("/instance/service-accounts", json={"name": "dp"}, headers=root).json()
        human = c.post("/instance/users", json={"email": "m@example.com"}, headers=root).json()
        assert human["service_account"] is False

        c.put(f"/instance/users/{created['id']}/orgs/o1", headers=root)
        minted = c.post(f"/instance/users/{created['id']}/tokens", json={"org_id": "o1"}, headers=root).json()
        org = {"authorization": f"Bearer {minted['token']}"}
        assert c.get("/org/keys", headers=org).status_code == 200
        c.delete(f"/instance/users/{created['id']}/orgs/o1", headers=root)
        assert c.get("/org/keys", headers=org).status_code == 401

        by_email = {u["email"]: u["service_account"] for u in c.get("/instance/users", headers=root).json()}
        assert by_email == {created["email"]: True, "m@example.com": False}


def test_membership_lifecycle_and_listing(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)
        c.post("/instance/orgs", json={"id": "o2"}, headers=root)
        user = c.post("/instance/users", json={"email": "m@example.com"}, headers=root).json()
        uid = user["id"]

        assert c.put(f"/instance/users/{uid}/orgs/o1", headers=root).status_code == 200
        assert c.put(f"/instance/users/{uid}/orgs/o2", headers=root).status_code == 200
        assert c.put(f"/instance/users/{uid}/orgs/o1", headers=root).status_code == 200
        assert c.put(f"/instance/users/{uid}/orgs/missing", headers=root).status_code == 404
        assert c.put("/instance/users/u-ghost/orgs/o1", headers=root).status_code == 404

        listed = c.get("/instance/users", headers=root).json()
        assert [u["id"] for u in listed] == [uid]
        assert listed[0]["orgs"] == ["o1", "o2"]

        assert c.delete(f"/instance/users/{uid}/orgs/o2", headers=root).status_code == 200
        assert c.delete(f"/instance/users/{uid}/orgs/o2", headers=root).status_code == 404
        assert c.get("/instance/users", headers=root).json()[0]["orgs"] == ["o1"]


def test_user_org_token_requires_membership(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)
        uid = c.post("/instance/users", json={"email": "m@example.com"}, headers=root).json()["id"]
        assert c.post(f"/instance/users/{uid}/tokens", json={"org_id": "o1"}, headers=root).status_code == 403
        c.put(f"/instance/users/{uid}/orgs/o1", headers=root)
        minted = c.post(f"/instance/users/{uid}/tokens", json={"org_id": "o1"}, headers=root).json()
        assert minted["org_id"] == "o1"
        assert minted["user_id"] == uid
        org = {"authorization": f"Bearer {minted['token']}"}
        assert c.post("/org/keys", json={}, headers=org).status_code == 200
        assert c.get("/org/keys", headers=org).status_code == 200


def test_instance_token_requires_instance_admin(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        member = c.post("/instance/users", json={"email": "m@example.com"}, headers=root).json()["id"]
        admin = c.post("/instance/users", json={"email": "a@example.com", "instance_admin": True}, headers=root).json()["id"]
        assert c.post(f"/instance/users/{member}/tokens", json={}, headers=root).status_code == 403
        minted = c.post(f"/instance/users/{admin}/tokens", json={}, headers=root).json()
        assert minted["org_id"] is None
        headers = {"authorization": f"Bearer {minted['token']}"}
        assert c.get("/instance/users", headers=headers).status_code == 200


def test_instance_admin_can_take_org_scope_without_membership(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)
        admin = c.post("/instance/users", json={"email": "a@example.com", "instance_admin": True}, headers=root).json()["id"]
        minted = c.post(f"/instance/users/{admin}/tokens", json={"org_id": "o1"}, headers=root).json()
        org = {"authorization": f"Bearer {minted['token']}"}
        assert c.get("/org/keys", headers=org).status_code == 200


def test_removing_membership_invalidates_user_tokens(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)
        uid = c.post("/instance/users", json={"email": "m@example.com"}, headers=root).json()["id"]
        c.put(f"/instance/users/{uid}/orgs/o1", headers=root)
        minted = c.post(f"/instance/users/{uid}/tokens", json={"org_id": "o1"}, headers=root).json()
        org = {"authorization": f"Bearer {minted['token']}"}
        assert c.get("/org/keys", headers=org).status_code == 200
        c.delete(f"/instance/users/{uid}/orgs/o1", headers=root)
        assert c.get("/org/keys", headers=org).status_code == 401


def test_token_listing_shows_the_owner(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/instance/orgs", json={"id": "o1"}, headers=root)
        uid = c.post("/instance/users", json={"email": "m@example.com"}, headers=root).json()["id"]
        c.put(f"/instance/users/{uid}/orgs/o1", headers=root)
        c.post(f"/instance/users/{uid}/tokens", json={"org_id": "o1"}, headers=root)
        ownerless = c.post("/instance/orgs/o1/tokens", headers=root).json()
        listed = {t["id"]: t["user_id"] for t in c.get("/instance/tokens", headers=root).json()}
        assert set(listed.values()) == {uid, None}
        assert listed[ownerless["token_id"]] is None
