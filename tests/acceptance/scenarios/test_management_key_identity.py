from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD

from contract import uuid7


def test_management_keys_keep_the_issuing_identity_over_http(stack):
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    assert stack.request().status_code == 200
    csrf = {"X-Requested-With": "XMLHttpRequest"}
    with httpx.Client(base_url=stack.cp_url, headers=csrf) as owner, httpx.Client(base_url=stack.cp_url, headers=csrf) as admin:
        owner_login = owner.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        owner_login.raise_for_status()
        owner_id = owner_login.json()["data"]["user_id"]
        invitation = owner.post(f"/api/v1/orgs/{stack.org_id}/invitations", json={"email": "org-admin@acceptance.test", "org_role": "admin"})
        invitation.raise_for_status()
        invitation_token = parse_qs(urlsplit(invitation.json()["data"]["url"]).fragment)["token"][0]
        signup = admin.post(
            "/api/v1/auth/signup",
            json={"email": "org-admin@acceptance.test", "name": "Org Admin", "password": ADMIN_PASSWORD, "invitation_token": invitation_token},
        )
        signup.raise_for_status()
        admin_id = signup.json()["data"]["user_id"]
        member_path = f"/api/v1/orgs/{stack.org_id}/users/{admin_id}"
        owner.put(member_path, json={"role": "admin"}).raise_for_status()
        key_path = f"/api/v1/orgs/{stack.org_id}/management-keys"
        body = {"label": "self-only", "permissions": ["management-keys.issue", "members.manage"]}
        assert admin.post(key_path, json={**body, "user_id": owner_id}).status_code == 422
        issued = admin.post(key_path, json=body)
        issued.raise_for_status()
        parent = issued.json()["data"]
        assert parent["user_id"] == admin_id
        with httpx.Client(base_url=stack.cp_url, headers={"authorization": f"Bearer {parent['token']}"}) as issuer:
            response = issuer.post(key_path, json={"label": "child", "permissions": ["members.manage"]})
            response.raise_for_status()
            child = response.json()["data"]
        assert child["user_id"] == admin_id
        assert child["parent_id"] == parent["id"]
        with httpx.Client(base_url=stack.cp_url, headers={"authorization": f"Bearer {child['token']}"}) as delegate:
            assert delegate.put(member_path, json={"role": "owner"}).status_code == 403
            owner.put(member_path, json={"role": "member"}).raise_for_status()
            assert delegate.put(member_path, json={"role": "admin"}).status_code == 403
            owner.delete(f"/api/v1/management-keys/{parent['id']}").raise_for_status()
            assert delegate.put(member_path, json={"role": "admin"}).status_code == 401
        service_account = owner.post(
            "/api/v1/service-accounts",
            json={"name": "Global Data Plane", "instance_role": "data_plane"},
        )
        service_account.raise_for_status()
        principal = service_account.json()["data"]
        credential = owner.post(
            f"/api/v1/service-accounts/{principal['id']}/management-keys",
            json={"label": "data-plane", "permissions": ["data-planes.heartbeat"]},
        )
        credential.raise_for_status()
        key = credential.json()["data"]
        assert key["user_id"] == principal["id"]
        with httpx.Client(base_url=stack.cp_url, headers={"authorization": f"Bearer {key['token']}"}) as data_plane:
            heartbeat = data_plane.post(
                "/api/v1/heartbeat",
                json={"instance_id": str(uuid7()), "version": "acceptance", "bundle_id": None},
            )
            heartbeat.raise_for_status()
    assert stack.request().status_code == 200
