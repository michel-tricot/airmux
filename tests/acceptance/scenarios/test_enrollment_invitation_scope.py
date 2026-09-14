from __future__ import annotations

import httpx
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD


def test_enrollment_hides_foreign_invitation_metadata_over_http(stack):
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    assert stack.request().status_code == 200
    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}) as browser:
        login = browser.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        login.raise_for_status()
        user_id = login.json()["data"]["user_id"]
        visible_org = browser.post("/api/v1/organizations", json={"name": "Visible invitations"})
        visible_org.raise_for_status()
        org_id = visible_org.json()["data"]["id"]
        private_org = browser.post("/api/v1/organizations", json={"name": "Private invitations"})
        private_org.raise_for_status()
        private_id = private_org.json()["data"]["id"]
        workspace = browser.post(f"/api/v1/organizations/{org_id}/workspaces", json={"name": "Selected"})
        workspace.raise_for_status()
        workspace_id = workspace.json()["data"]["id"]
        body = {"email": ADMIN_EMAIL, "org_role": "member"}
        browser.post(
            f"/api/v1/organizations/{org_id}/invitations", json={**body, "workspace_id": workspace_id, "workspace_role": "viewer"}
        ).raise_for_status()
        browser.post(f"/api/v1/organizations/{private_id}/invitations", json=body).raise_for_status()
        browser.put(f"/api/v1/organizations/{org_id}/users/{user_id}", json={"role": "owner"}).raise_for_status()
        personal = browser.get("/api/v1/enroll")
        personal.raise_for_status()
        assert {invitation["org_id"] for invitation in personal.json()["data"]["pending_invitations"]} == {org_id, private_id}
        for prefix in (f"/api/v1/organizations/{org_id}", f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}"):
            issued = browser.post(f"{prefix}/management-keys", json={"label": "enrollment", "permissions": ["workspaces.read"]})
            issued.raise_for_status()
            token = issued.json()["data"]["token"]
            with httpx.Client(base_url=stack.cp_url, headers={"authorization": f"Bearer {token}"}) as credential:
                response = credential.get("/api/v1/enroll")
                response.raise_for_status()
                enrollment = response.json()["data"]
                assert [org["id"] for org in enrollment["orgs"]] == [org_id]
                assert [invitation["org_id"] for invitation in enrollment["pending_invitations"]] == [org_id]
                assert private_id not in response.text
                assert "Private invitations" not in response.text
    assert stack.request().status_code == 200
