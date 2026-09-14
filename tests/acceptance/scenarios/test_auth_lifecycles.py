from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import yaml
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import Stack

CSRF = {"X-Requested-With": "XMLHttpRequest"}
MEMBER_EMAIL = "lifecycle@acceptance.test"
MEMBER_PASSWORD = "lifecycle-password"


def start(stack: Stack) -> None:
    stack.write_config(poll_interval_s=1)
    configuration = yaml.safe_load(stack.config_path.read_text())
    configuration["control_plane"]["throttling"] = {
        "authentication": {"burst": 20, "per_second": 10},
        "account": {"burst": 20, "per_second": 10},
    }
    stack.config_path.write_text(yaml.safe_dump(configuration))
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()


def concurrently(first: Callable[[], httpx.Response], second: Callable[[], httpx.Response]) -> tuple[httpx.Response, httpx.Response]:
    barrier = Barrier(2, timeout=10)

    def invoke(action: Callable[[], httpx.Response]) -> httpx.Response:
        barrier.wait()
        return action()

    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = (executor.submit(invoke, first), executor.submit(invoke, second))
        return pending[0].result(timeout=15), pending[1].result(timeout=15)


@pytest.mark.parametrize("competing_action", ["accept", "revoke", "reissue"])
def test_invitation_competing_transitions_preserve_one_membership(stack: Stack, competing_action: str) -> None:
    start(stack)
    with (
        httpx.Client(base_url=stack.cp_url, headers=CSRF, timeout=10) as admin,
        httpx.Client(base_url=stack.cp_url, headers=CSRF, timeout=10) as member,
    ):
        admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).raise_for_status()
        invitation = admin.post(f"/api/v1/organizations/{stack.org_id}/invitations", json={"email": MEMBER_EMAIL, "org_role": "member"})
        invitation.raise_for_status()
        minted = invitation.json()["data"]
        token = parse_qs(urlsplit(minted["url"]).fragment)["token"][0]
        signup = member.post("/api/v1/auth/signup", json={"email": MEMBER_EMAIL, "password": MEMBER_PASSWORD, "invitation_token": token})
        signup.raise_for_status()
        user_id = signup.json()["data"]["user_id"]
        invitation_path = f"/api/v1/organizations/{stack.org_id}/invitations/{minted['invitation']['id']}"

        def accept() -> httpx.Response:
            return member.post("/api/v1/enroll/invitations/accept", json={"token": token})

        def compete() -> httpx.Response:
            return accept() if competing_action == "accept" else admin.post(f"{invitation_path}/{competing_action}")

        accepted, competing = concurrently(accept, compete)
        if competing_action == "accept":
            assert (accepted.status_code, competing.status_code) == (200, 200)
        elif accepted.status_code == 200:
            assert competing.status_code == 409
        else:
            assert competing.status_code == 200, competing.text
            assert accepted.status_code == (410 if competing_action == "revoke" else 404)
        members = admin.get(f"/api/v1/organizations/{stack.org_id}/users")
        members.raise_for_status()
        memberships = [membership for membership in members.json()["data"] if membership["user_id"] == user_id]
        assert len(memberships) == (1 if accepted.status_code == 200 else 0)
        replay = accept()
        assert replay.status_code == accepted.status_code
        assert token not in members.text
        assert stack.request().status_code == 200


@pytest.mark.parametrize("competing_action", ["approval", "delivery"])
def test_cli_competing_transitions_deliver_one_usable_credential(stack: Stack, competing_action: str) -> None:
    start(stack)
    with httpx.Client(base_url=stack.cp_url, headers=CSRF, timeout=10) as admin:
        admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).raise_for_status()
        started = admin.post("/api/v1/auth/cli/start", json={"client_name": "lifecycle-concurrency"})
        started.raise_for_status()
        auth_request = started.json()["data"]

        def approve() -> httpx.Response:
            return admin.post("/api/v1/auth/cli/approve", json={"user_code": auth_request["user_code"], "org_id": stack.org_id})

        def poll() -> httpx.Response:
            return admin.post("/api/v1/auth/cli/poll", json={"poll_secret": auth_request["poll_secret"]})

        pending = poll()
        assert pending.json()["data"]["status"] == "pending"
        assert pending.json()["data"]["token"] is None
        if competing_action == "approval":
            responses = concurrently(approve, approve)
            assert sorted(response.status_code for response in responses) == [200, 409]
            delivered = poll()
        else:
            approve().raise_for_status()
            responses = concurrently(poll, poll)
            assert sorted(response.status_code for response in responses) == [200, 404]
            delivered = next(response for response in responses if response.status_code == 200)
        delivered.raise_for_status()
        token = delivered.json()["data"]["token"]
        headers = {"authorization": f"Bearer {token}"}
        assert httpx.get(f"{stack.cp_url}/api/v1/organizations/{stack.org_id}/workspaces", headers=headers).status_code == 200
        assert poll().status_code == 404
        keys = admin.get(f"/api/v1/organizations/{stack.org_id}/management-keys")
        keys.raise_for_status()
        minted = [key for key in keys.json()["data"] if key["label"] == "lifecycle-concurrency"]
        assert len(minted) == 1
        assert token not in keys.text
        admin.delete(f"/api/v1/management-keys/{minted[0]['id']}").raise_for_status()
        assert httpx.get(f"{stack.cp_url}/api/v1/organizations/{stack.org_id}/workspaces", headers=headers).status_code == 401
        assert stack.request().status_code == 200


def test_password_change_closes_a_concurrent_old_password_login(stack: Stack) -> None:
    start(stack)
    with (
        httpx.Client(base_url=stack.cp_url, headers=CSRF, timeout=10) as current,
        httpx.Client(base_url=stack.cp_url, headers=CSRF, timeout=10) as competing,
    ):
        current.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).raise_for_status()
        changed, logged_in = concurrently(
            lambda: current.post("/api/v1/auth/password", json={"current_password": ADMIN_PASSWORD, "new_password": MEMBER_PASSWORD}),
            lambda: competing.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}),
        )
        assert changed.status_code == 200, changed.text
        assert logged_in.status_code in {200, 401}
        assert competing.get("/api/v1/auth/me").status_code == 401
        assert current.get("/api/v1/auth/me").status_code == 200
        competing.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": MEMBER_PASSWORD}).raise_for_status()
        assert competing.get("/api/v1/auth/me").status_code == 200
        assert stack.request().status_code == 200
