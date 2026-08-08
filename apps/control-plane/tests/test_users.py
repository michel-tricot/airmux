from __future__ import annotations

import re
from uuid import UUID

from fastapi.testclient import TestClient
from helpers import FIXTURE_ADMIN_EMAIL, make_admin, make_org, make_workspace, run_in_db, setup_control_plane

from contract import uuid7
from control_plane.models import User, set_actor


def _users(c, headers):
    """Instance user listing minus the fixture admin that headers() creates."""
    return [u for u in c.get("/v1/users", headers=headers).json()["data"] if u["email"] != FIXTURE_ADMIN_EMAIL]


def test_claim_is_public_and_flips_on_the_first_human(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        assert c.get("/v1/instance/oss/claim").json()["data"] == {"claimed": False}

        async def make_service_account():
            sa = User.new_service_account("dp")
            await set_actor(sa.id)
            await sa.save()

        run_in_db(tmp_path, make_service_account)
        assert c.get("/v1/instance/oss/claim").json()["data"] == {"claimed": False}

        assert c.post("/v1/auth/signup", json={"email": "first@example.com", "name": "", "password": "hunter2-hunter2"}).status_code == 200
        assert c.get("/v1/instance/oss/claim").json()["data"] == {"claimed": True}


def test_user_create_returns_full_resource_with_server_id(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        created = c.post("/v1/users", json={"email": "michel@example.com"}, headers=root).json()["data"]
        assert UUID(created["id"]).version == 7
        assert created["email"] == "michel@example.com"
        assert created["name"] == "michel@example.com"
        assert "instance_admin" not in created
        assert created["orgs"] == []
        assert c.post("/v1/users", json={"email": "michel@example.com"}, headers=root).status_code == 409


def test_service_account_gets_a_derived_email(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        created = c.post("/v1/service-accounts", json={"name": "Data Plane"}, headers=root).json()["data"]
        assert created["service_account"] is True
        assert created["name"] == "Data Plane"
        assert re.fullmatch(r"data-plane-[0-9a-f]{8}@airbytesvcaccount\.ai", created["email"])
        again = c.post("/v1/service-accounts", json={"name": "Data Plane"}, headers=root).json()["data"]
        assert again["email"] != created["email"]
        assert c.post("/v1/service-accounts", json={"name": "!!"}, headers=root).status_code == 422


def test_service_account_is_a_full_principal(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        created = c.post("/v1/service-accounts", json={"name": "dp"}, headers=root).json()["data"]
        human = c.post("/v1/users", json={"email": "m@example.com"}, headers=root).json()["data"]
        assert human["service_account"] is False

        c.put(f"/v1/users/{created['id']}/orgs/{o1}", headers=root)
        minted = c.post("/v1/org/management-keys", json={"user_id": created["id"], "label": "t"}, headers=cp.headers(o1)).json()["data"]
        org = {"authorization": f"Bearer {minted['token']}"}
        assert c.get("/v1/org/workspaces", headers=org).status_code == 200
        c.delete(f"/v1/users/{created['id']}/orgs/{o1}", headers=root)
        assert c.get("/v1/org/workspaces", headers=org).status_code == 401

        by_email = {u["email"]: u["service_account"] for u in _users(c, root)}
        assert by_email == {created["email"]: True, "m@example.com": False}


def test_membership_lifecycle_and_listing(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        user = c.post("/v1/users", json={"email": "m@example.com"}, headers=root).json()["data"]
        uid = user["id"]

        assert c.put(f"/v1/users/{uid}/orgs/{o1}", headers=root).status_code == 200
        assert c.put(f"/v1/users/{uid}/orgs/{o2}", headers=root).status_code == 200
        assert c.put(f"/v1/users/{uid}/orgs/{o1}", headers=root).status_code == 200
        assert c.put(f"/v1/users/{uid}/orgs/{uuid7()}", headers=root).status_code == 404
        assert c.put(f"/v1/users/{uuid7()}/orgs/{o1}", headers=root).status_code == 404

        listed = _users(c, root)
        assert [u["id"] for u in listed] == [uid]
        assert sorted(listed[0]["orgs"]) == sorted([str(o1), str(o2)])

        deleted = c.delete(f"/v1/users/{uid}/orgs/{o2}", headers=root).json()["data"]
        assert deleted["id"] == f"{uid}/{o2}"
        assert deleted["deleted_at"] is not None
        assert c.delete(f"/v1/users/{uid}/orgs/{o2}", headers=root).status_code == 404
        assert _users(c, root)[0]["orgs"] == [str(o1)]


def test_user_org_token_requires_membership(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        uid = c.post("/v1/users", json={"email": "m@example.com"}, headers=root).json()["data"]["id"]
        assert c.post("/v1/org/management-keys", json={"user_id": uid, "label": "t"}, headers=cp.headers(o1)).status_code == 403
        c.put(f"/v1/users/{uid}/orgs/{o1}", headers=root)
        minted = c.post("/v1/org/management-keys", json={"user_id": uid, "label": "t"}, headers=cp.headers(o1)).json()["data"]
        assert minted["org_id"] == str(o1)
        assert minted["user_id"] == uid
        org = {"authorization": f"Bearer {minted['token']}"}
        ws = make_workspace(c, org)
        assert c.post(f"/v1/org/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=org).status_code == 200
        assert c.get(f"/v1/org/workspaces/{ws}/inference-keys", headers=org).status_code == 200


def test_instance_token_requires_instance_admin(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        member = c.post("/v1/users", json={"email": "m@example.com"}, headers=root).json()["data"]["id"]
        admin = c.post("/v1/users", json={"email": "a@example.com"}, headers=root).json()["data"]["id"]
        make_admin(tmp_path, admin)
        assert c.post("/v1/instance/management-keys", json={"user_id": member, "label": "t"}, headers=root).status_code == 403
        minted = c.post("/v1/instance/management-keys", json={"user_id": admin, "label": "t"}, headers=root).json()["data"]
        assert minted["org_id"] is None
        headers = {"authorization": f"Bearer {minted['token']}"}
        assert c.get("/v1/users", headers=headers).status_code == 200


def test_instance_admin_can_take_org_scope_without_membership(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        admin = c.post("/v1/users", json={"email": "a@example.com"}, headers=root).json()["data"]["id"]
        make_admin(tmp_path, admin)
        minted = c.post("/v1/org/management-keys", json={"user_id": admin, "label": "t"}, headers=cp.headers(o1)).json()["data"]
        org = {"authorization": f"Bearer {minted['token']}"}
        assert c.get("/v1/org/workspaces", headers=org).status_code == 200


def test_removing_membership_invalidates_user_tokens(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        uid = c.post("/v1/users", json={"email": "m@example.com"}, headers=root).json()["data"]["id"]
        c.put(f"/v1/users/{uid}/orgs/{o1}", headers=root)
        minted = c.post("/v1/org/management-keys", json={"user_id": uid, "label": "t"}, headers=cp.headers(o1)).json()["data"]
        org = {"authorization": f"Bearer {minted['token']}"}
        assert c.get("/v1/org/workspaces", headers=org).status_code == 200
        c.delete(f"/v1/users/{uid}/orgs/{o1}", headers=root)
        assert c.get("/v1/org/workspaces", headers=org).status_code == 401


def test_token_listing_shows_the_owner(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        uid = c.post("/v1/users", json={"email": "m@example.com"}, headers=root).json()["data"]["id"]
        c.put(f"/v1/users/{uid}/orgs/{o1}", headers=root)
        minted = c.post("/v1/org/management-keys", json={"user_id": uid, "label": "t"}, headers=cp.headers(o1)).json()["data"]
        listed = {t["id"]: t["user_id"] for t in c.get("/v1/instance/management-keys", headers=root).json()["data"]}
        assert listed[minted["id"]] == uid
        assert all(owner for owner in listed.values())
