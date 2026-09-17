from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlparse

from fastapi.testclient import TestClient
from helpers import captured_sql, make_org, make_workspace, run_in_db, setup_control_plane

from control_plane.models import OrgInvitation, set_actor

CSRF = {"X-Requested-With": "fetch"}


PASSWORD = "hunter2-hunter2"


def _client(cp) -> TestClient:
    return TestClient(cp.app, base_url="https://testserver")


def _token(url: str) -> str:
    fragment = urlparse(url).fragment
    key, separator, value = fragment.partition("=")
    assert (key, separator) == ("token", "=")
    return unquote(value)


def _issue(client: TestClient, cp, org_id, **body):
    payload = {"email": "invitee@example.com", "org_role": "member", **body}
    response = client.post(f"/api/v1/organizations/{org_id}/invitations", json=payload, headers=cp.headers(org_id))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_invitation_link_is_revealed_once_and_only_its_hash_is_stored(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as client:
        org_id = make_org(client, cp.headers(), "Acme")
        invitation = _issue(client, cp, org_id, email=" Invitee@Example.COM ")
        token = _token(invitation["url"])

        assert invitation["invitation"]["email"] == "invitee@example.com"
        assert invitation["invitation"]["status"] == "pending"
        assert token.startswith("invite_")
        listed = client.get(f"/api/v1/organizations/{org_id}/invitations", headers=cp.headers(org_id)).json()["data"]
        assert [item["id"] for item in listed] == [invitation["invitation"]["id"]]
        assert token not in str(listed)

    stored = run_in_db(tmp_path, OrgInvitation.find)[0]
    assert stored.token_hash != token


def test_invitation_preview_and_accept_create_both_memberships_atomically(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as client:
        org_id = make_org(client, cp.headers(), "Acme")
        workspace_id = make_workspace(client, cp.headers(org_id), "Production")
        minted = _issue(client, cp, org_id, workspace_id=str(workspace_id), workspace_role="viewer")
        token = _token(minted["url"])

        with captured_sql(cp.app) as statements:
            preview = client.post("/api/v1/enroll/invitations/preview", json={"token": token})
        assert preview.status_code == 200, preview.text
        assert len([statement for statement in statements if statement.lstrip().startswith("SELECT")]) <= 1
        assert preview.json()["data"] == {
            "email": "invitee@example.com",
            "org_id": str(org_id),
            "org_name": "Acme",
            "org_role": "member",
            "workspace_id": str(workspace_id),
            "workspace_name": "Production",
            "workspace_role": "viewer",
            "expires_at": minted["invitation"]["expires_at"],
        }

        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": "INVITEE@example.com", "name": "Invitee", "password": PASSWORD},
        )
        assert signup.status_code == 200, signup.text
        user_id = signup.json()["data"]["user_id"]
        with captured_sql(cp.app) as acceptance_statements:
            accepted = client.post("/api/v1/enroll/invitations/accept", json={"token": token}, headers=CSRF)
        assert accepted.status_code == 200, accepted.text
        assert not [
            statement
            for statement in acceptance_statements
            if statement.lstrip().startswith("SELECT") and ("FROM org_membership" in statement or "FROM workspace_membership" in statement)
        ]
        membership_inserts = [
            statement
            for statement in acceptance_statements
            if statement.startswith(("INSERT INTO org_membership", "INSERT INTO workspace_membership"))
        ]
        assert len(membership_inserts) == 2
        assert all("ON CONFLICT" in statement and "DO NOTHING" in statement for statement in membership_inserts)
        assert accepted.json()["data"] == {
            "invitation_id": minted["invitation"]["id"],
            "org_id": str(org_id),
            "workspace_id": str(workspace_id),
            "status": "accepted",
        }

        org_members = client.get(f"/api/v1/organizations/{org_id}/users", headers=cp.headers(org_id)).json()["data"]
        assert [(member["user_id"], member["role"]) for member in org_members] == [(user_id, "member")]
        workspace_members = client.get(
            f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/members",
            headers=cp.headers(org_id),
        ).json()["data"]
        assert [(member["user_id"], member["role"]) for member in workspace_members] == [(user_id, "viewer")]
        assert client.post("/api/v1/enroll/invitations/accept", json={"token": token}, headers=CSRF).status_code == 200


def test_valid_invitation_allows_signup_when_public_signup_is_closed(tmp_path):
    cp = setup_control_plane(tmp_path, public_signup=False)
    with _client(cp) as client:
        org_id = make_org(client, cp.headers(), "Acme")
        token = _token(_issue(client, cp, org_id)["url"])

        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": "INVITEE@example.com", "name": "Invitee", "password": PASSWORD, "invitation_token": token},
        )

        assert signup.status_code == 200, signup.text
        assert signup.json()["data"]["email"] == "invitee@example.com"
        assert signup.json()["data"]["orgs"] == []
        assert client.post("/api/v1/enroll/invitations/accept", json={"token": token}, headers=CSRF).status_code == 200


def test_closed_signup_rejects_invalid_unavailable_and_mismatched_invitations(tmp_path):
    cp = setup_control_plane(tmp_path, public_signup=False)
    with _client(cp) as client:
        org_id = make_org(client, cp.headers(), "Acme")
        minted = _issue(client, cp, org_id)
        token = _token(minted["url"])

        invalid = client.post(
            "/api/v1/auth/signup",
            json={"email": "invitee@example.com", "name": "Invitee", "password": PASSWORD, "invitation_token": "invite_invalid"},
        )
        mismatch = client.post(
            "/api/v1/auth/signup",
            json={"email": "someone-else@example.com", "name": "Other", "password": PASSWORD, "invitation_token": token},
        )
        client.post(
            f"/api/v1/organizations/{org_id}/invitations/{minted['invitation']['id']}/revoke",
            headers=cp.headers(org_id),
        )
        revoked = client.post(
            "/api/v1/auth/signup",
            json={"email": "invitee@example.com", "name": "Invitee", "password": PASSWORD, "invitation_token": token},
        )

        assert invalid.status_code == 404
        assert mismatch.status_code == 403
        assert revoked.status_code == 410


def test_new_account_sees_its_pending_invitations_in_enrollment(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as client:
        org_id = make_org(client, cp.headers(), "Acme")
        workspace_id = make_workspace(client, cp.headers(org_id), "Production")
        minted = _issue(
            client,
            cp,
            org_id,
            email=" Invitee@Example.COM ",
            workspace_id=str(workspace_id),
            workspace_role="viewer",
        )
        token = _token(minted["url"])
        _issue(client, cp, org_id, email="someone-else@example.com")
        expired_org_id = make_org(client, cp.headers(), "Expired")
        _issue(client, cp, expired_org_id, email="invitee@example.com")

        async def expire_invitation():
            invitation = await OrgInvitation.active_for_email(expired_org_id, "invitee@example.com")
            assert invitation is not None
            assert invitation.created_by_user_id is not None
            await set_actor(invitation.created_by_user_id)
            invitation.expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
            await invitation.save()

        run_in_db(tmp_path, expire_invitation)

        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": "INVITEE@example.com", "name": "Invitee", "password": PASSWORD},
        )
        assert signup.status_code == 200, signup.text

        enrollment = client.get("/api/v1/enroll", headers=CSRF)
        assert enrollment.status_code == 200, enrollment.text
        assert enrollment.json()["data"]["pending_invitations"] == [
            {
                "email": "invitee@example.com",
                "org_id": str(org_id),
                "org_name": "Acme",
                "org_role": "member",
                "workspace_id": str(workspace_id),
                "workspace_name": "Production",
                "workspace_role": "viewer",
                "expires_at": minted["invitation"]["expires_at"],
            }
        ]

        assert client.post("/api/v1/enroll/invitations/accept", json={"token": token}, headers=CSRF).status_code == 200
        assert client.get("/api/v1/enroll", headers=CSRF).json()["data"]["pending_invitations"] == []


def test_wrong_account_cannot_accept_and_does_not_consume_the_invitation(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as client:
        org_id = make_org(client, cp.headers(), "Acme")
        token = _token(_issue(client, cp, org_id)["url"])
        assert (
            client.post(
                "/api/v1/auth/signup",
                json={"email": "other@example.com", "name": "Other", "password": PASSWORD},
            ).status_code
            == 200
        )

        mismatch = client.post("/api/v1/enroll/invitations/accept", json={"token": token}, headers=CSRF)
        assert mismatch.status_code == 403
        client.post("/api/v1/auth/logout", headers=CSRF)
        client.cookies.clear()
        assert (
            client.post(
                "/api/v1/auth/signup",
                json={"email": "invitee@example.com", "name": "Invitee", "password": PASSWORD},
            ).status_code
            == 200
        )
        assert client.post("/api/v1/enroll/invitations/accept", json={"token": token}, headers=CSRF).status_code == 200


def test_reissue_invalidates_the_old_link_and_revoke_blocks_the_new_one(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as client:
        org_id = make_org(client, cp.headers(), "Acme")
        minted = _issue(client, cp, org_id)
        old_token = _token(minted["url"])
        invitation_id = minted["invitation"]["id"]

        reissued = client.post(
            f"/api/v1/organizations/{org_id}/invitations/{invitation_id}/reissue",
            headers=cp.headers(org_id),
        )
        assert reissued.status_code == 200, reissued.text
        new_token = _token(reissued.json()["data"]["url"])
        assert new_token != old_token
        assert client.post("/api/v1/enroll/invitations/preview", json={"token": old_token}).status_code == 404

        revoked = client.post(
            f"/api/v1/organizations/{org_id}/invitations/{invitation_id}/revoke",
            headers=cp.headers(org_id),
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["data"]["status"] == "revoked"
        assert client.post("/api/v1/enroll/invitations/preview", json={"token": new_token}).status_code == 410


def test_expired_invitation_can_be_reissued_but_not_accepted(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as client:
        org_id = make_org(client, cp.headers(), "Acme")
        minted = _issue(client, cp, org_id)
        token = _token(minted["url"])

        async def expire():
            invitation = (await OrgInvitation.find())[0]
            assert invitation.created_by_user_id is not None
            await set_actor(invitation.created_by_user_id)
            invitation.expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
            await invitation.save()

        run_in_db(tmp_path, expire)
        assert client.post("/api/v1/enroll/invitations/preview", json={"token": token}).status_code == 410
        invitation_id = minted["invitation"]["id"]
        assert (
            client.post(
                f"/api/v1/organizations/{org_id}/invitations/{invitation_id}/reissue",
                headers=cp.headers(org_id),
            ).status_code
            == 200
        )


def test_only_org_member_managers_can_invite_and_existing_members_use_direct_membership(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as client:
        org_id = make_org(client, cp.headers(), "Acme")
        member = client.post(
            "/api/v1/auth/signup",
            json={"email": "member@example.com", "name": "Member", "password": PASSWORD},
        ).json()["data"]
        assert (
            client.put(
                f"/api/v1/organizations/{org_id}/users/{member['user_id']}",
                json={"role": "member"},
                headers=cp.headers(org_id),
            ).status_code
            == 200
        )
        member_headers = cp.headers_for(org_id, member["user_id"])
        denied = client.post(
            f"/api/v1/organizations/{org_id}/invitations",
            json={"email": "new@example.com", "org_role": "member"},
            headers=member_headers,
        )
        assert denied.status_code == 403

        existing = client.post(
            f"/api/v1/organizations/{org_id}/invitations",
            json={"email": "member@example.com", "org_role": "member"},
            headers=cp.headers(org_id),
        )
        assert existing.status_code == 409


def test_invitation_rejects_machine_roles_and_cross_org_workspaces(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as client:
        first = make_org(client, cp.headers(), "First")
        second = make_org(client, cp.headers(), "Second")
        workspace_id = make_workspace(client, cp.headers(second), "Other")

        assert (
            client.post(
                f"/api/v1/organizations/{first}/invitations",
                json={"email": "invitee@example.com", "org_role": "data_plane"},
                headers=cp.headers(first),
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/v1/organizations/{first}/invitations",
                json={
                    "email": "invitee@example.com",
                    "org_role": "member",
                    "workspace_id": str(workspace_id),
                    "workspace_role": "member",
                },
                headers=cp.headers(first),
            ).status_code
            == 404
        )
