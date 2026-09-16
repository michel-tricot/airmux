from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, setup_control_plane

CSRF = {"X-Requested-With": "fetch"}


@pytest.mark.parametrize("invited_workspace", ["selected", "sibling", "none"])
def test_enrollment_limits_invitation_metadata_to_credential_scope(tmp_path, invited_workspace):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app, base_url="https://testserver") as client:
        first = make_org(client, root, "visible-org")
        second = make_org(client, root, "private-org")
        selected = make_workspace(client, cp.headers(first), "selected")
        sibling = make_workspace(client, cp.headers(first), "private-workspace")
        signup = client.post("/api/v1/auth/signup", json={"email": "invitee@example.com", "name": "Invitee", "password": "test-password-long"})
        assert signup.status_code == 200, signup.text
        user_id = signup.json()["data"]["user_id"]
        workspace_id = selected if invited_workspace == "selected" else sibling if invited_workspace == "sibling" else None
        body = {"email": "invitee@example.com", "org_role": "member"}
        local = client.post(
            f"/api/v1/organizations/{first}/invitations",
            headers=root,
            json={**body, **({"workspace_id": str(workspace_id), "workspace_role": "viewer"} if workspace_id else {})},
        )
        assert local.status_code == 200, local.text
        assert client.post(f"/api/v1/organizations/{second}/invitations", headers=root, json=body).status_code == 200
        assert client.put(f"/api/v1/organizations/{first}/users/{user_id}", headers=root, json={"role": "admin"}).status_code == 200
        browser = client.get("/api/v1/enroll/invitations", headers=CSRF).json()["data"]
        assert {invitation["org_id"] for invitation in browser} == {str(first), str(second)}
        org_bearer = cp.headers_for(first, user_id)
        org_view = client.get("/api/v1/enroll", headers=org_bearer)
        assert org_view.status_code == 200, org_view.text
        orgs = client.get("/api/v1/enroll/organizations", headers=org_bearer)
        invitations = client.get("/api/v1/enroll/invitations", headers=org_bearer)
        assert [org["id"] for org in orgs.json()["data"]] == [str(first)]
        assert [invitation["org_id"] for invitation in invitations.json()["data"]] == [str(first)]
        assert "private-org" not in orgs.text
        assert "private-org" not in invitations.text
        workspace_bearer = cp.headers_for(first, user_id, selected)
        workspace_view = client.get("/api/v1/enroll", headers=workspace_bearer)
        assert workspace_view.status_code == 200, workspace_view.text
        invitations_response = client.get("/api/v1/enroll/invitations", headers=workspace_bearer)
        invitations = invitations_response.json()["data"]
        assert [invitation["workspace_id"] for invitation in invitations] == ([str(selected)] if invited_workspace == "selected" else [])
        assert "private-org" not in invitations_response.text
        assert "private-workspace" not in invitations_response.text
        assert "token_hash" not in invitations_response.text
