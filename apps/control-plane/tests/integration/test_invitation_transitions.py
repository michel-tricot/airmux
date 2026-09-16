from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from helpers import run_in_db, setup_control_plane

from control_plane.models import OrgInvitation, set_actor

CSRF = {"X-Requested-With": "fetch"}
PASSWORD = "transition-password"


@pytest.mark.parametrize(
    ("transition", "preview_status", "accept_status"), [("expired", 410, 410), ("revoked", 410, 410), ("reissued", 404, 404), ("accepted", 410, 200)]
)
def test_invitation_terminal_states_have_consistent_preview_and_redemption(tmp_path, transition, preview_status, accept_status):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app, base_url="https://testserver") as client:
        signup = client.post("/api/v1/auth/signup", json={"email": "owner@transition.test", "password": PASSWORD})
        assert signup.status_code == 200
        owner_id = UUID(signup.json()["data"]["user_id"])
        owner_headers = {**CSRF, "cookie": f"airmux_session={client.cookies['airmux_session']}"}
        org = client.post("/api/v1/enroll/org", json={"name": "Transitions"}, headers=owner_headers).json()["data"]
        invited = client.post(
            f"/api/v1/organizations/{org['id']}/invitations", json={"email": "member@transition.test", "org_role": "member"}, headers=owner_headers
        )
        assert invited.status_code == 200
        invitation = invited.json()["data"]
        token = parse_qs(urlsplit(invitation["url"]).fragment)["token"][0]
        assert client.post("/api/v1/auth/signup", json={"email": "member@transition.test", "password": PASSWORD}).status_code == 200
        path = f"/api/v1/organizations/{org['id']}/invitations/{invitation['invitation']['id']}"
        if transition == "expired":

            async def expire():
                await set_actor(owner_id)
                pending = await OrgInvitation.find_by_id(UUID(invitation["invitation"]["id"]))
                assert pending is not None
                pending.expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
                await pending.save()

            run_in_db(tmp_path, expire)
        elif transition == "accepted":
            assert client.post("/api/v1/enroll/invitations/accept", json={"token": token}, headers=CSRF).status_code == 200
        else:
            action = "revoke" if transition == "revoked" else "reissue"
            assert client.post(f"{path}/{action}", headers=owner_headers).status_code == 200
        assert client.post("/api/v1/enroll/invitations/preview", json={"token": token}).status_code == preview_status
        assert client.post("/api/v1/enroll/invitations/accept", json={"token": token}, headers=CSRF).status_code == accept_status
        available = client.get(f"/api/v1/organizations/{org['id']}/invitations", headers=owner_headers)
        assert available.status_code == 200
        assert token not in available.text
