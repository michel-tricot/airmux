from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import httpx
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD

CSRF = {"X-Requested-With": "XMLHttpRequest"}


def test_owner_changes_keep_instance_and_organization_authority_live(stack):
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    assert stack.request().status_code == 200

    with httpx.Client(base_url=stack.cp_url, headers=CSRF) as founder, httpx.Client(base_url=stack.cp_url, headers=CSRF) as successor:
        founder_login = founder.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        founder_login.raise_for_status()
        founder_id = founder_login.json()["data"]["user_id"]

        invitation = founder.post(
            f"/api/v1/organizations/{stack.org_id}/invitations",
            json={"email": "successor@acceptance.test", "org_role": "member"},
        )
        invitation.raise_for_status()
        invitation_token = parse_qs(urlsplit(invitation.json()["data"]["url"]).fragment)["token"][0]
        successor_login = successor.post(
            "/api/v1/auth/signup",
            json={
                "email": "successor@acceptance.test",
                "name": "Successor",
                "password": ADMIN_PASSWORD,
                "invitation_token": invitation_token,
            },
        )
        successor_login.raise_for_status()
        successor_id = successor_login.json()["data"]["user_id"]

        founder.put(f"/api/v1/users/{successor_id}/instance-role", json={"instance_role": "owner"}).raise_for_status()
        founder.put(f"/api/v1/users/{founder_id}/instance-role", json={"instance_role": "auditor"}).raise_for_status()
        refused = successor.put(f"/api/v1/users/{successor_id}/instance-role", json={"instance_role": None})
        assert refused.status_code == 409, refused.text
        assert successor.get("/api/v1/instance/oss/claim").json()["data"]["claimed"] is True

        organization = successor.post("/api/v1/organizations", json={"name": "Ownership race"})
        organization.raise_for_status()
        org_id = organization.json()["data"]["id"]
        for user_id in (founder_id, successor_id):
            successor.put(f"/api/v1/organizations/{org_id}/users/{user_id}", json={"role": "owner"}).raise_for_status()
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = [
                attempt.result()
                for attempt in [
                    pool.submit(successor.put, f"/api/v1/organizations/{org_id}/users/{user_id}", json={"role": "member"})
                    for user_id in (founder_id, successor_id)
                ]
            ]
        assert sorted(response.status_code for response in responses) == [200, 409]

    assert stack.request().status_code == 200
