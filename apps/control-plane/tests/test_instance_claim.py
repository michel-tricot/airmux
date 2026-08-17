"""The first human on a deployment claims it; everyone after is an ordinary account."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from helpers import run_in_db, setup_control_plane

from control_plane.models import User, set_actor

PASSWORD = "correct horse battery"


def _signup(client, email):
    return client.post("/api/v1/auth/signup", json={"email": email, "name": email, "password": PASSWORD})


def test_the_first_human_claims_the_instance(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        assert c.get("/api/v1/instance/oss/claim").json()["data"]["claimed"] is False

        founder = _signup(c, "founder@example.com")
        assert founder.status_code == 200, founder.text
        assert founder.json()["data"]["instance_role"] == "owner"

        assert c.get("/api/v1/instance/oss/claim").json()["data"]["claimed"] is True


def test_later_signups_are_ordinary_accounts(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        _signup(c, "founder@example.com")
        c.post("/api/v1/auth/logout")

        second = _signup(c, "later@example.com")
        assert second.status_code == 200, second.text
        assert second.json()["data"]["instance_role"] is None


def test_the_founder_reaches_the_instance_endpoints_and_others_do_not(tmp_path):
    """The point of the claim: a fresh deployment has an admin without anyone touching the database."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        _signup(c, "founder@example.com")
        headers = {"X-Requested-With": "XMLHttpRequest"}
        assert c.get("/api/v1/orgs", headers=headers).status_code == 200

        c.post("/api/v1/auth/logout", headers=headers)
        _signup(c, "later@example.com")
        assert c.get("/api/v1/orgs", headers=headers).status_code == 403


def test_racing_signups_produce_one_owner(tmp_path):
    """Two founders arriving at once: the advisory lock serializes the claim, so the second sees the first."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = [f.result() for f in [pool.submit(_signup, c, f"racer{i}@example.com") for i in range(2)]]

        assert [r.status_code for r in responses] == [200, 200]
        assert sorted((r.json()["data"]["instance_role"] or "none") for r in responses) == ["none", "owner"]


def test_a_service_account_does_not_claim_the_instance(tmp_path):
    """Service accounts are machine principals; a deployment holding only them is still unclaimed.

    The account goes in through the model rather than the API, because creating one over the API
    already needs the admin this test is about.
    """
    cp = setup_control_plane(tmp_path)

    async def add_robot():
        robot = User.new_service_account("robot")
        await set_actor(robot.id)
        await robot.save()

    run_in_db(tmp_path, add_robot)

    with TestClient(cp.app) as c:
        assert c.get("/api/v1/instance/oss/claim").json()["data"]["claimed"] is False
        assert _signup(c, "founder@example.com").json()["data"]["instance_role"] == "owner"
