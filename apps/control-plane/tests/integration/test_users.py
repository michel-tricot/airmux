from __future__ import annotations

import re

from fastapi.testclient import TestClient
from helpers import FIXTURE_ADMIN_EMAIL, make_admin, make_org, make_user, run_in_db, setup_control_plane

from contract import uuid7
from control_plane.authz import DATA_PLANE_PERMISSIONS, InstanceRole, Permission
from control_plane.models import DataPlaneInstance, User, set_actor


def _users(c, headers):
    """Instance user listing minus the fixture admin that headers() creates."""
    return [u for u in c.get("/api/v1/users", headers=headers).json()["data"] if u["email"] != FIXTURE_ADMIN_EMAIL]


def test_claim_is_public_and_flips_on_the_first_human(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        assert c.get("/api/v1/instance/oss/claim").json()["data"] == {"claimed": False, "public_signup": True}

        async def make_service_account():
            sa = User.new_service_account("dp")
            await set_actor(sa.id)
            await sa.save()

        run_in_db(tmp_path, make_service_account)
        assert c.get("/api/v1/instance/oss/claim").json()["data"] == {"claimed": False, "public_signup": True}

        assert c.post("/api/v1/auth/signup", json={"email": "first@example.com", "name": "", "password": "hunter2-hunter2"}).status_code == 200
        assert c.get("/api/v1/instance/oss/claim").json()["data"] == {"claimed": True, "public_signup": True}


def test_human_accounts_can_only_be_created_through_signup(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        assert c.post("/api/v1/users", json={"email": "michel@example.com"}, headers=root).status_code == 405


def test_service_account_gets_a_derived_email(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        created = c.post("/api/v1/service-accounts", json={"name": "Data Plane"}, headers=root).json()["data"]
        assert created["service_account"] is True
        assert created["name"] == "Data Plane"
        assert re.fullmatch(r"data-plane-[0-9a-f]{8}@service-account\.airllm\.invalid", created["email"])
        again = c.post("/api/v1/service-accounts", json={"name": "Data Plane"}, headers=root).json()["data"]
        assert again["email"] != created["email"]
        assert c.post("/api/v1/service-accounts", json={"name": "!!"}, headers=root).status_code == 422
        assert c.post("/api/v1/service-accounts", json={"name": ""}, headers=root).status_code == 422
        assert c.post("/api/v1/service-accounts", json={"name": "x" * 201}, headers=root).status_code == 422


def test_service_account_can_hold_any_instance_role(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        created = c.post(
            "/api/v1/service-accounts",
            json={"name": "Global Data Plane", "instance_role": InstanceRole.data_plane},
            headers=root,
        )
        assert created.status_code == 200, created.text
        principal = created.json()["data"]
        assert principal["instance_role"] == InstanceRole.data_plane
        owner = c.post(
            "/api/v1/service-accounts",
            json={"name": "Automation Owner", "instance_role": InstanceRole.owner},
            headers=root,
        )
        assert owner.status_code == 200, owner.text
        assert owner.json()["data"]["instance_role"] == InstanceRole.owner

        minted = c.post(
            "/api/v1/instance/access-keys",
            json={"user_id": principal["id"], "label": "data-plane", "permissions": sorted(DATA_PLANE_PERMISSIONS)},
            headers=root,
        )
        assert minted.status_code == 200, minted.text
        token = minted.json()["data"]
        assert token["scope"]["level"] == "instance"
        instance_id = uuid7()
        heartbeat = {"instance_id": str(instance_id), "version": "0.1.0", "bundle_id": None}
        assert c.post("/api/v1/heartbeat", json=heartbeat, headers={"authorization": f"Bearer {token['token']}"}).status_code == 200
        instance = run_in_db(tmp_path, lambda: DataPlaneInstance.get(instance_id))
        assert instance is not None
        assert instance.org_id is None


def test_service_account_is_a_full_principal(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        created = c.post("/api/v1/service-accounts", json={"name": "dp"}, headers=root).json()["data"]
        make_user(tmp_path, "m@example.com")

        c.put(f"/api/v1/orgs/{o1}/users/{created['id']}", json={"role": "data_plane"}, headers=cp.headers(o1))
        minted = c.post(
            f"/api/v1/orgs/{o1}/access-keys",
            json={
                "user_id": created["id"],
                "label": "data-plane",
                "permissions": sorted(DATA_PLANE_PERMISSIONS),
            },
            headers=root,
        ).json()["data"]
        org = {"authorization": f"Bearer {minted['token']}"}
        assert c.get(f"/api/v1/orgs/{o1}/workspaces", headers=org).status_code == 403
        heartbeat = {"instance_id": str(uuid7()), "version": "0.1.0", "bundle_id": None}
        assert c.post("/api/v1/heartbeat", json=heartbeat, headers=org).status_code == 200
        c.delete(f"/api/v1/orgs/{o1}/users/{created['id']}", headers=cp.headers(o1))
        assert c.post("/api/v1/heartbeat", json=heartbeat, headers=org).status_code == 403

        by_email = {u["email"]: u["service_account"] for u in _users(c, root)}
        assert by_email == {created["email"]: True, "m@example.com": False}


def test_listing_filters_by_principal_kind(tmp_path):
    """The filter is a server-side one so a caller after service accounts does not read every human."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        account = c.post("/api/v1/service-accounts", json={"name": "dp"}, headers=root).json()["data"]
        make_user(tmp_path, "m@example.com")

        def emails(params):
            return [u["email"] for u in c.get("/api/v1/users", params=params, headers=root).json()["data"] if u["email"] != FIXTURE_ADMIN_EMAIL]

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

        assert c.put(f"/api/v1/orgs/{o1}/users/{uid}", json={"role": "member"}, headers=cp.headers(o1)).status_code == 200
        assert c.put(f"/api/v1/orgs/{o2}/users/{uid}", json={"role": "member"}, headers=cp.headers(o2)).status_code == 200
        assert c.put(f"/api/v1/orgs/{o1}/users/{uid}", json={"role": "member"}, headers=cp.headers(o1)).status_code == 200
        assert c.put(f"/api/v1/orgs/{o1}/users/{uuid7()}", json={"role": "member"}, headers=cp.headers(o1)).status_code == 404

        listed = _users(c, root)
        assert [u["id"] for u in listed] == [uid]
        assert sorted(listed[0]["orgs"]) == sorted([str(o1), str(o2)])

        deleted = c.delete(f"/api/v1/orgs/{o2}/users/{uid}", headers=cp.headers(o2)).json()["data"]
        assert deleted["id"] == f"{uid}/{o2}"
        assert deleted["deleted_at"] is not None
        assert c.delete(f"/api/v1/orgs/{o2}/users/{uid}", headers=cp.headers(o2)).status_code == 404
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
            assert c.put(f"/api/v1/orgs/{org}/users/{user}", json={"role": "member"}, headers=cp.headers(org)).status_code == 200

        first = c.get(f"/api/v1/orgs/{o1}/users", headers=cp.headers(o1)).json()["data"]
        assert [m["user_id"] for m in first] == [both]
        assert first[0]["email"] == "both@example.com"
        assert first[0]["name"] == "Both"
        assert first[0]["status"] == "member"
        assert "orgs" not in first[0]

        second = c.get(f"/api/v1/orgs/{o2}/users", headers=cp.headers(o2)).json()["data"]
        assert sorted(m["email"] for m in second) == ["both@example.com", "two@example.com"]


def test_org_users_require_an_explicit_scope(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        uid = str(make_user(tmp_path, "m@example.com").id)
        assert c.get("/api/v1/org/users", headers=root).status_code == 404
        assert c.get(f"/api/v1/orgs/{o1}/users", headers=root).status_code == 200
        assert c.put(f"/api/v1/orgs/{o1}/users/{uid}", json={"role": "member"}, headers=root).status_code == 200
        assert c.delete(f"/api/v1/orgs/{o1}/users/{uid}", headers=root).status_code == 200
        assert c.put(f"/api/v1/users/{uid}/orgs/{o1}", headers=root).status_code == 404


def test_org_access_key_requires_standing_membership(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "o1")
        user_id = str(make_user(tmp_path, "m@example.com").id)
        body = {
            "user_id": user_id,
            "label": "member",
            "permissions": [Permission.organizations_read],
        }
        assert client.post(f"/api/v1/orgs/{org_id}/access-keys", json=body, headers=root).status_code == 403
        client.put(f"/api/v1/orgs/{org_id}/users/{user_id}", json={"role": "member"}, headers=cp.headers(org_id))
        minted = client.post(f"/api/v1/orgs/{org_id}/access-keys", json=body, headers=root)
        assert minted.status_code == 200, minted.text
        key = minted.json()["data"]
        assert key["org_id"] == str(org_id)
        assert key["user_id"] == user_id
        headers = {"authorization": f"Bearer {key['token']}"}
        assert client.get(f"/api/v1/orgs/{org_id}/workspaces", headers=headers).status_code == 200


def test_instance_access_key_requires_an_instance_role(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        member = str(make_user(tmp_path, "m@example.com").id)
        owner = str(make_user(tmp_path, "a@example.com").id)
        make_admin(tmp_path, owner)
        body = {"label": "instance", "permissions": [Permission.principals_read]}
        assert client.post("/api/v1/instance/access-keys", json={**body, "user_id": member}, headers=root).status_code == 403
        minted = client.post("/api/v1/instance/access-keys", json={**body, "user_id": owner}, headers=root)
        assert minted.status_code == 200, minted.text
        headers = {"authorization": f"Bearer {minted.json()['data']['token']}"}
        assert client.get("/api/v1/users", headers=headers).status_code == 200


def test_instance_owner_can_use_an_org_scope_without_membership(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "o1")
        owner = str(make_user(tmp_path, "a@example.com").id)
        make_admin(tmp_path, owner)
        minted = client.post(
            f"/api/v1/orgs/{org_id}/access-keys",
            json={
                "user_id": owner,
                "label": "org",
                "permissions": [Permission.workspaces_read],
            },
            headers=root,
        )
        assert minted.status_code == 200, minted.text
        headers = {"authorization": f"Bearer {minted.json()['data']['token']}"}
        assert client.get(f"/api/v1/orgs/{org_id}/workspaces", headers=headers).status_code == 200


def test_removing_membership_removes_effective_key_authority(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "o1")
        user_id = str(make_user(tmp_path, "m@example.com").id)
        client.put(f"/api/v1/orgs/{org_id}/users/{user_id}", json={"role": "member"}, headers=cp.headers(org_id))
        minted = client.post(
            f"/api/v1/orgs/{org_id}/access-keys",
            json={
                "user_id": user_id,
                "label": "member",
                "permissions": [Permission.organizations_read],
            },
            headers=root,
        ).json()["data"]
        headers = {"authorization": f"Bearer {minted['token']}"}
        assert client.get(f"/api/v1/orgs/{org_id}/workspaces", headers=headers).status_code == 200
        client.delete(f"/api/v1/orgs/{org_id}/users/{user_id}", headers=cp.headers(org_id))
        assert client.get(f"/api/v1/orgs/{org_id}/workspaces", headers=headers).status_code == 403


def test_access_key_listing_shows_the_principal(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "o1")
        user_id = str(make_user(tmp_path, "m@example.com").id)
        client.put(f"/api/v1/orgs/{org_id}/users/{user_id}", json={"role": "member"}, headers=cp.headers(org_id))
        minted = client.post(
            f"/api/v1/orgs/{org_id}/access-keys",
            json={
                "user_id": user_id,
                "label": "member",
                "permissions": [Permission.organizations_read],
            },
            headers=root,
        ).json()["data"]
        listed = {key["id"]: key["user_id"] for key in client.get("/api/v1/instance/access-keys", headers=root).json()["data"]}
        assert listed[minted["id"]] == user_id
        assert all(principal for principal in listed.values())


def test_instance_role_change_updates_authority_and_can_clear_role(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    user = make_user(tmp_path, "roles@example.com")
    with TestClient(cp.app) as client:
        for role in ("owner", "auditor", "data_plane", None):
            changed = client.put(f"/api/v1/users/{user.id}/instance-role", json={"instance_role": role}, headers=root)
            assert changed.status_code == 200, changed.text
            assert changed.json()["data"]["instance_role"] == role
            assert client.get(f"/api/v1/users/{user.id}", headers=root).json()["data"]["instance_role"] == role


def test_instance_role_change_rejects_invalid_input_and_missing_user(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    user = make_user(tmp_path, "roles@example.com")
    with TestClient(cp.app) as client:
        for body in ({}, {"instance_role": "admin"}, {"instance_role": "owner", "name": "changed"}):
            assert client.put(f"/api/v1/users/{user.id}/instance-role", json=body, headers=root).status_code == 422
        assert client.put(f"/api/v1/users/{uuid7()}/instance-role", json={"instance_role": None}, headers=root).status_code == 404


def test_last_instance_owner_cannot_be_demoted(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        owner = next(user for user in client.get("/api/v1/users", headers=root).json()["data"] if user["email"] == FIXTURE_ADMIN_EMAIL)
        response = client.put(f"/api/v1/users/{owner['id']}/instance-role", json={"instance_role": None}, headers=root)
        assert response.status_code == 409
        assert client.get(f"/api/v1/users/{owner['id']}", headers=root).json()["data"]["instance_role"] == "owner"


def test_role_changes_require_instance_management_and_take_effect_immediately(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app, base_url="https://testserver") as client:
        user_id = client.post("/api/v1/auth/signup", json={"email": "roles@example.com", "name": "Roles", "password": "hunter2-hunter2"}).json()[
            "data"
        ]["user_id"]
        path = f"/api/v1/users/{user_id}/instance-role"
        csrf = {"X-Requested-With": "fetch"}
        assert client.put(path, json={"instance_role": "owner"}, headers=csrf).status_code == 403
        assert client.put(path, json={"instance_role": "owner"}, headers=root).status_code == 200
        assert client.get("/api/v1/users", headers=csrf).status_code == 200
        assert client.put(path, json={"instance_role": "auditor"}, headers=csrf).status_code == 200
        assert client.put(path, json={"instance_role": "owner"}, headers=csrf).status_code == 403
        assert client.put(path, json={"instance_role": None}, headers=root).status_code == 200
        assert client.get("/api/v1/users", headers=csrf).status_code == 403


def test_managed_service_account_cannot_gain_instance_role(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "managed")

        async def managed_account():
            await set_actor(actor_id)
            return await User.new_service_account("Managed", managing_org_id=org_id).save()

        actor_id = make_user(tmp_path, "actor@example.com").id
        user = run_in_db(tmp_path, managed_account)
        response = client.put(f"/api/v1/users/{user.id}/instance-role", json={"instance_role": "owner"}, headers=root)
        assert response.status_code == 409
        assert client.get(f"/api/v1/users/{user.id}", headers=root).json()["data"]["instance_role"] is None
