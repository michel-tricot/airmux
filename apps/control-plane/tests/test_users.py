from __future__ import annotations

import re

from fastapi.testclient import TestClient
from helpers import FIXTURE_ADMIN_EMAIL, make_admin, make_org, make_user, run_in_db, setup_control_plane

from contract import uuid7
from control_plane.authz import DATA_PLANE_PERMISSIONS, Permission
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


def test_human_accounts_can_only_be_created_through_signup(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        assert c.post("/v1/users", json={"email": "michel@example.com"}, headers=root).status_code == 405


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
        assert c.post("/v1/service-accounts", json={"name": ""}, headers=root).status_code == 422
        assert c.post("/v1/service-accounts", json={"name": "x" * 201}, headers=root).status_code == 422


def test_service_account_is_a_full_principal(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        created = c.post("/v1/service-accounts", json={"name": "dp"}, headers=root).json()["data"]
        make_user(tmp_path, "m@example.com")

        c.put(f"/v1/org/users/{created['id']}", json={"role": "data_plane"}, headers=cp.headers(o1))
        minted = c.post(
            "/v1/access-keys",
            json={
                "user_id": created["id"],
                "org_id": str(o1),
                "label": "data-plane",
                "permissions": sorted(DATA_PLANE_PERMISSIONS),
            },
            headers=root,
        ).json()["data"]
        org = {"authorization": f"Bearer {minted['token']}"}
        assert c.get("/v1/org/workspaces", headers=org).status_code == 403
        heartbeat = {"instance_id": str(uuid7()), "version": "0.1.0", "bundle_id": None}
        assert c.post("/v1/heartbeat", json=heartbeat, headers=org).status_code == 200
        c.delete(f"/v1/org/users/{created['id']}", headers=cp.headers(o1))
        assert c.post("/v1/heartbeat", json=heartbeat, headers=org).status_code == 403

        by_email = {u["email"]: u["service_account"] for u in _users(c, root)}
        assert by_email == {created["email"]: True, "m@example.com": False}


def test_listing_filters_by_principal_kind(tmp_path):
    """The filter is a server-side one so a caller after service accounts does not read every human."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        account = c.post("/v1/service-accounts", json={"name": "dp"}, headers=root).json()["data"]
        make_user(tmp_path, "m@example.com")

        def emails(params):
            return [u["email"] for u in c.get("/v1/users", params=params, headers=root).json()["data"] if u["email"] != FIXTURE_ADMIN_EMAIL]

        assert emails({"service_account": True}) == [account["email"]]
        assert emails({"service_account": False}) == ["m@example.com"]
        assert sorted(emails({})) == sorted([account["email"], "m@example.com"])


def test_membership_lifecycle_and_listing(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        uid = str(make_user(tmp_path, "m@example.com").id)

        assert c.put(f"/v1/org/users/{uid}", json={"role": "member"}, headers=cp.headers(o1)).status_code == 200
        assert c.put(f"/v1/org/users/{uid}", json={"role": "member"}, headers=cp.headers(o2)).status_code == 200
        assert c.put(f"/v1/org/users/{uid}", json={"role": "member"}, headers=cp.headers(o1)).status_code == 200
        assert c.put(f"/v1/org/users/{uuid7()}", json={"role": "member"}, headers=cp.headers(o1)).status_code == 404

        listed = _users(c, root)
        assert [u["id"] for u in listed] == [uid]
        assert sorted(listed[0]["orgs"]) == sorted([str(o1), str(o2)])

        deleted = c.delete(f"/v1/org/users/{uid}", headers=cp.headers(o2)).json()["data"]
        assert deleted["id"] == f"{uid}/{o2}"
        assert deleted["deleted_at"] is not None
        assert c.delete(f"/v1/org/users/{uid}", headers=cp.headers(o2)).status_code == 404
        assert _users(c, root)[0]["orgs"] == [str(o1)]


def test_org_user_listing_is_scoped_to_the_acting_org(tmp_path):
    """The roster an org credential can read, and the cross-org membership it deliberately cannot."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        both = str(make_user(tmp_path, "both@example.com", "Both").id)
        only_two = str(make_user(tmp_path, "two@example.com").id)
        for org, user in ((o1, both), (o2, both), (o2, only_two)):
            assert c.put(f"/v1/org/users/{user}", json={"role": "member"}, headers=cp.headers(org)).status_code == 200

        first = c.get("/v1/org/users", headers=cp.headers(o1)).json()["data"]
        assert [m["user_id"] for m in first] == [both]
        assert first[0]["email"] == "both@example.com"
        assert first[0]["name"] == "Both"
        assert first[0]["status"] == "member"
        assert "orgs" not in first[0]

        second = c.get("/v1/org/users", headers=cp.headers(o2)).json()["data"]
        assert sorted(m["email"] for m in second) == ["both@example.com", "two@example.com"]


def test_org_users_are_unreachable_without_org_scope(tmp_path):
    """Membership moved off the instance router; an instance credential has no org to act on."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        uid = str(make_user(tmp_path, "m@example.com").id)
        assert c.get("/v1/org/users", headers=root).status_code == 403
        assert c.put(f"/v1/org/users/{uid}", json={"role": "member"}, headers=root).status_code == 403
        assert c.delete(f"/v1/org/users/{uid}", headers=root).status_code == 403
        assert c.put(f"/v1/users/{uid}/orgs/{o1}", headers=root).status_code == 404


def test_org_access_key_requires_standing_membership(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "o1")
        user_id = str(make_user(tmp_path, "m@example.com").id)
        body = {
            "user_id": user_id,
            "org_id": str(org_id),
            "label": "member",
            "permissions": [Permission.workspaces_read],
        }
        assert client.post("/v1/access-keys", json=body, headers=root).status_code == 403
        client.put(f"/v1/org/users/{user_id}", json={"role": "member"}, headers=cp.headers(org_id))
        minted = client.post("/v1/access-keys", json=body, headers=root)
        assert minted.status_code == 200, minted.text
        key = minted.json()["data"]
        assert key["org_id"] == str(org_id)
        assert key["user_id"] == user_id
        headers = {"authorization": f"Bearer {key['token']}"}
        assert client.get("/v1/org/workspaces", headers=headers).status_code == 200


def test_instance_access_key_requires_an_instance_role(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        member = str(make_user(tmp_path, "m@example.com").id)
        owner = str(make_user(tmp_path, "a@example.com").id)
        make_admin(tmp_path, owner)
        body = {"label": "instance", "permissions": [Permission.principals_read]}
        assert client.post("/v1/access-keys", json={**body, "user_id": member}, headers=root).status_code == 403
        minted = client.post("/v1/access-keys", json={**body, "user_id": owner}, headers=root)
        assert minted.status_code == 200, minted.text
        headers = {"authorization": f"Bearer {minted.json()['data']['token']}"}
        assert client.get("/v1/users", headers=headers).status_code == 200


def test_instance_owner_can_use_an_org_boundary_without_membership(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "o1")
        owner = str(make_user(tmp_path, "a@example.com").id)
        make_admin(tmp_path, owner)
        minted = client.post(
            "/v1/access-keys",
            json={
                "user_id": owner,
                "org_id": str(org_id),
                "label": "org",
                "permissions": [Permission.workspaces_read],
            },
            headers=root,
        )
        assert minted.status_code == 200, minted.text
        headers = {"authorization": f"Bearer {minted.json()['data']['token']}"}
        assert client.get("/v1/org/workspaces", headers=headers).status_code == 200


def test_removing_membership_removes_effective_key_authority(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "o1")
        user_id = str(make_user(tmp_path, "m@example.com").id)
        client.put(f"/v1/org/users/{user_id}", json={"role": "member"}, headers=cp.headers(org_id))
        minted = client.post(
            "/v1/access-keys",
            json={
                "user_id": user_id,
                "org_id": str(org_id),
                "label": "member",
                "permissions": [Permission.workspaces_read],
            },
            headers=root,
        ).json()["data"]
        headers = {"authorization": f"Bearer {minted['token']}"}
        assert client.get("/v1/org/workspaces", headers=headers).status_code == 200
        client.delete(f"/v1/org/users/{user_id}", headers=cp.headers(org_id))
        assert client.get("/v1/org/workspaces", headers=headers).status_code == 403


def test_access_key_listing_shows_the_principal(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "o1")
        user_id = str(make_user(tmp_path, "m@example.com").id)
        client.put(f"/v1/org/users/{user_id}", json={"role": "member"}, headers=cp.headers(org_id))
        minted = client.post(
            "/v1/access-keys",
            json={
                "user_id": user_id,
                "org_id": str(org_id),
                "label": "member",
                "permissions": [Permission.workspaces_read],
            },
            headers=root,
        ).json()["data"]
        listed = {key["id"]: key["user_id"] for key in client.get("/v1/access-keys", headers=root).json()["data"]}
        assert listed[minted["id"]] == user_id
        assert all(principal for principal in listed.values())
