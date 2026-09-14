from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from helpers import make_admin, make_org, make_user, run_in_db, setup_control_plane

from control_plane.authz import InstanceRole
from control_plane.models import OrgMembership, User, set_actor
from control_plane.models.user import LastInstanceOwnerError

CSRF = {"X-Requested-With": "fetch"}
PASSWORD = "owner-test-password"


def _signup(client: TestClient, email: str):
    return client.post("/api/v1/auth/signup", json={"email": email, "name": email, "password": PASSWORD})


def test_last_instance_owner_cannot_be_deleted(tmp_path):
    cp = setup_control_plane(tmp_path, public_signup=False)
    with TestClient(cp.app, base_url="https://testserver") as client:
        founder = _signup(client, "founder@example.com")
        assert founder.status_code == 200, founder.text
        user_id = founder.json()["data"]["user_id"]

        deleted = client.delete(f"/api/v1/users/{user_id}", headers=CSRF)

        assert deleted.status_code == 409, deleted.text
        assert client.get("/api/v1/instance/oss/claim").json()["data"]["claimed"] is True


def test_instance_claim_survives_replacing_the_human_owner_with_a_service_account(tmp_path):
    cp = setup_control_plane(tmp_path, public_signup=False)
    with TestClient(cp.app, base_url="https://testserver") as client:
        founder = _signup(client, "founder@example.com").json()["data"]
        replacement = client.post(
            "/api/v1/service-accounts",
            json={"name": "Recovery", "instance_role": "owner"},
            headers=CSRF,
        )
        assert replacement.status_code == 200, replacement.text

        deleted = client.delete(f"/api/v1/users/{founder['user_id']}", headers=CSRF)

        assert deleted.status_code == 200, deleted.text
        assert client.get("/api/v1/instance/oss/claim").json()["data"]["claimed"] is True
        refused = _signup(client, "attacker@example.com")
        assert refused.status_code == 403, refused.text


def test_concurrent_organization_owner_demotions_keep_one_owner(tmp_path):
    cp = setup_control_plane(tmp_path)
    first = make_user(tmp_path, "first@example.com")
    second = make_user(tmp_path, "second@example.com")
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        for user in (first, second):
            added = client.put(f"/api/v1/orgs/{org_id}/users/{user.id}", headers=root, json={"role": "owner"})
            assert added.status_code == 200, added.text

        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [
                pool.submit(client.put, f"/api/v1/orgs/{org_id}/users/{user.id}", headers=root, json={"role": "member"}) for user in (first, second)
            ]
            responses = [attempt.result() for attempt in attempts]

    assert sorted(response.status_code for response in responses) == [200, 409]
    owners = run_in_db(tmp_path, lambda: OrgMembership.find(OrgMembership.org_id == org_id, OrgMembership.role == "owner"))
    assert len(owners) == 1


def test_concurrent_instance_owner_delete_and_demotion_keep_one_owner(tmp_path):
    setup_control_plane(tmp_path)
    first = make_user(tmp_path, "first@example.com")
    second = make_user(tmp_path, "second@example.com")
    make_admin(tmp_path, first.id)
    make_admin(tmp_path, second.id)

    async def delete_first():
        await set_actor(first.id)
        user = await User.find_by_id(first.id)
        assert user is not None
        try:
            await user.delete_with_contents()
        except LastInstanceOwnerError:
            return 409
        return 200

    async def demote_second():
        await set_actor(second.id)
        try:
            await User.change_instance_role(second.id, InstanceRole.auditor)
        except LastInstanceOwnerError:
            return 409
        return 200

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [
            pool.submit(run_in_db, tmp_path, delete_first),
            pool.submit(run_in_db, tmp_path, demote_second),
        ]
        responses = [attempt.result() for attempt in attempts]

    assert sorted(responses) == [200, 409]
    owners = run_in_db(tmp_path, lambda: User.find(User.instance_role == "owner"))
    assert len(owners) == 1
