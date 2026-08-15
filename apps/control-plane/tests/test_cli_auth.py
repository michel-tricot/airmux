from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

from fastapi.testclient import TestClient
from helpers import make_org, run_in_db, setup_control_plane

from control_plane.keys import MANAGEMENT_KEY_PREFIX
from control_plane.models import CliAuthRequest

CSRF = {"X-Requested-With": "fetch"}
PASSWORD = "hunter2-hunter2"


def _client(cp) -> TestClient:
    return TestClient(cp.app, base_url="https://testserver")


def _signup_with_org(c, email="m@example.com", org_name="mine"):
    me = c.post("/v1/auth/signup", json={"email": email, "name": email, "password": PASSWORD}).json()["data"]
    org = c.post("/v1/enroll/org", json={"name": org_name}, headers=CSRF).json()["data"]
    return me, org


def _start(c, client_name="mbp"):
    resp = c.post("/v1/auth/cli/start", json={"client_name": client_name})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_device_flow_end_to_end(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        _, org = _signup_with_org(c)
        started = _start(c)
        assert f"/cli?code={started['user_code']}" in started["verification_url"]

        pending = c.post("/v1/auth/cli/poll", json={"poll_secret": started["poll_secret"]})
        assert pending.json()["data"]["status"] == "pending"

        details = c.get(f"/v1/auth/cli/request?code={started['user_code']}", headers=CSRF)
        assert details.status_code == 200
        assert details.json()["data"]["client_name"] == "mbp"

        assert c.post("/v1/auth/cli/approve", json={"user_code": "XXXX-XXXX", "org_id": org["id"]}, headers=CSRF).status_code == 404
        approved = c.post("/v1/auth/cli/approve", json={"user_code": started["user_code"].lower(), "org_id": org["id"]}, headers=CSRF)
        assert approved.status_code == 200, approved.text
        assert c.get(f"/v1/auth/cli/request?code={started['user_code']}", headers=CSRF).status_code == 409

        done = c.post("/v1/auth/cli/poll", json={"poll_secret": started["poll_secret"]}).json()["data"]
        assert done["status"] == "complete"
        assert done["token"].startswith(MANAGEMENT_KEY_PREFIX)
        assert done["org_id"] == org["id"]
        assert done["org_name"] == "mine"

        bearer = {"authorization": f"Bearer {done['token']}"}
        assert c.get("/v1/org/workspaces", headers=bearer).status_code == 200
        assert c.post("/v1/auth/cli/poll", json={"poll_secret": started["poll_secret"]}).status_code == 404


def test_two_simultaneous_polls_deliver_one_key(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        _, org = _signup_with_org(c)
        started = _start(c)
        assert c.post("/v1/auth/cli/approve", json={"user_code": started["user_code"], "org_id": org["id"]}, headers=CSRF).status_code == 200
        barrier = Barrier(2)

        def poll():
            barrier.wait()
            return c.post("/v1/auth/cli/poll", json={"poll_secret": started["poll_secret"]})

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = [future.result() for future in (executor.submit(poll), executor.submit(poll))]

        assert sorted(response.status_code for response in responses) == [200, 404]
        complete = next(response.json()["data"] for response in responses if response.status_code == 200)
        assert complete["status"] == "complete"
        assert complete["token"].startswith(MANAGEMENT_KEY_PREFIX)


def test_reapproving_from_the_same_client_replaces_the_previous_key(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        _, org = _signup_with_org(c)

        def login_once() -> str:
            started = _start(c, client_name="mbp")
            assert c.post("/v1/auth/cli/approve", json={"user_code": started["user_code"], "org_id": org["id"]}, headers=CSRF).status_code == 200
            return c.post("/v1/auth/cli/poll", json={"poll_secret": started["poll_secret"]}).json()["data"]["token"]

        first = login_once()
        assert c.get("/v1/org/workspaces", headers={"authorization": f"Bearer {first}"}).status_code == 200
        second = login_once()
        assert c.get("/v1/org/workspaces", headers={"authorization": f"Bearer {second}"}).status_code == 200
        assert c.get("/v1/org/workspaces", headers={"authorization": f"Bearer {first}"}).status_code == 401


def test_approval_requires_membership_and_a_browser_session(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        other_org = make_org(c, root, "other")
        _signup_with_org(c)
        started = _start(c)
        no_membership = c.post("/v1/auth/cli/approve", json={"user_code": started["user_code"], "org_id": str(other_org)}, headers=CSRF)
        assert no_membership.status_code == 403

    with _client(cp) as anonymous:
        started_body = {"user_code": started["user_code"], "org_id": str(other_org)}
        assert anonymous.post("/v1/auth/cli/approve", json=started_body, headers={**CSRF, **root}).status_code == 401


def test_expired_requests_are_gone_from_both_sides(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        _, org = _signup_with_org(c)
        started = _start(c)

        async def expire():
            auth_request = (await CliAuthRequest.find())[0]
            auth_request.expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
            await auth_request.save()

        run_in_db(tmp_path, expire)
        assert c.post("/v1/auth/cli/poll", json={"poll_secret": started["poll_secret"]}).status_code == 410
        assert c.post("/v1/auth/cli/approve", json={"user_code": started["user_code"], "org_id": org["id"]}, headers=CSRF).status_code == 410
        assert c.get(f"/v1/auth/cli/request?code={started['user_code']}", headers=CSRF).status_code == 410
        _start(c)
        assert len(run_in_db(tmp_path, CliAuthRequest.find)) == 1


def test_deleting_an_approved_org_removes_its_device_request(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        user = c.post("/v1/auth/signup", json={"email": "member@example.com", "password": PASSWORD}).json()["data"]
        org_id = make_org(c, root, "temporary")
        assert c.put(f"/v1/org/users/{user['user_id']}", headers=cp.headers(org_id)).status_code == 200
        started = _start(c)
        assert c.post("/v1/auth/cli/approve", json={"user_code": started["user_code"], "org_id": str(org_id)}, headers=CSRF).status_code == 200

        deleted = c.delete(f"/v1/orgs/{org_id}", headers=root)

        assert deleted.status_code == 200, deleted.text
        assert c.post("/v1/auth/cli/poll", json={"poll_secret": started["poll_secret"]}).status_code == 404
        assert run_in_db(tmp_path, CliAuthRequest.find) == []


def test_deleting_an_approver_removes_their_device_request(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        user = c.post("/v1/auth/signup", json={"email": "member@example.com", "password": PASSWORD}).json()["data"]
        org_id = make_org(c, root, "kept")
        org = cp.headers(org_id)
        assert c.put(f"/v1/org/users/{user['user_id']}", headers=org).status_code == 200
        started = _start(c)
        assert c.post("/v1/auth/cli/approve", json={"user_code": started["user_code"], "org_id": str(org_id)}, headers=CSRF).status_code == 200
        assert c.delete(f"/v1/org/users/{user['user_id']}", headers=org).status_code == 200

        deleted = c.delete(f"/v1/users/{user['user_id']}", headers=root)

        assert deleted.status_code == 200, deleted.text
        assert c.post("/v1/auth/cli/poll", json={"poll_secret": started["poll_secret"]}).status_code == 404
        assert run_in_db(tmp_path, CliAuthRequest.find) == []
