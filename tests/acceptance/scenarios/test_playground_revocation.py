from __future__ import annotations

import time
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, MODEL

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import Stack


def wait_for_status(request: Callable[[], httpx.Response], status: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if request().status_code == status:
            return
        time.sleep(0.1)
    pytest.fail(f"Request did not reach HTTP {status} within {timeout} seconds")


def invite_playground_member(admin: httpx.Client, member: httpx.Client, org_path: str, workspace_id: str) -> str:
    invitation = admin.post(
        f"{org_path}/invitations",
        json={"email": "member@acceptance.test", "org_role": "member", "workspace_id": workspace_id, "workspace_role": "admin"},
    )
    invitation.raise_for_status()
    invitation_token = parse_qs(urlsplit(invitation.json()["data"]["url"]).fragment)["token"][0]
    signup = member.post(
        "/api/v1/auth/signup",
        json={"email": "member@acceptance.test", "password": "playground-password", "invitation_token": invitation_token},
    )
    signup.raise_for_status()
    member.post("/api/v1/enroll/invitations/accept", json={"token": invitation_token}).raise_for_status()
    return signup.json()["data"]["user_id"]


@pytest.mark.parametrize("loss", ["workspace_removal", "workspace_demotion", "org_removal", "logout", "end", "key", "parent"])
def test_playground_authority_loss_reaches_running_data_plane(stack: Stack, loss: str) -> None:
    stack.write_config(poll_interval_s=1)
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    csrf = {"X-Requested-With": "XMLHttpRequest"}
    with (
        httpx.Client(base_url=stack.cp_url, headers=csrf, timeout=10.0) as admin,
        httpx.Client(base_url=stack.cp_url, headers=csrf, timeout=10.0) as member,
    ):
        admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).raise_for_status()
        org_path = f"/api/v1/orgs/{stack.org_id}"
        workspace_id = admin.get(f"{org_path}/workspaces").json()["data"][0]["id"]
        workspace_path = f"{org_path}/workspaces/{workspace_id}"
        user_id = invite_playground_member(admin, member, org_path, workspace_id)
        key_id = None
        if loss in {"key", "parent"}:
            key = member.post(
                f"{workspace_path}/management-keys",
                json={"label": "playground", "permissions": ["playground.execute", "management-keys.issue"]},
            )
            key.raise_for_status()
            key_id = key.json()["data"]["id"]
            member.headers["authorization"] = f"Bearer {key.json()['data']['token']}"
            if loss == "parent":
                child = member.post(f"{workspace_path}/management-keys", json={"label": "child", "permissions": ["playground.execute"]})
                child.raise_for_status()
                member.headers["authorization"] = f"Bearer {child.json()['data']['token']}"
        playground = member.put(f"{workspace_path}/playground-session")
        playground.raise_for_status()
        cookie = member.cookies["airllm_playground"]

        def inference() -> httpx.Response:
            return httpx.post(
                f"{stack.dp_url}/inf/v1/chat/completions",
                headers={**csrf, "cookie": f"airllm_playground={cookie}"},
                json={"model": MODEL, "messages": [{"role": "user", "content": "revocation probe"}]},
                timeout=2.0,
            )

        wait_for_status(inference, 200)
        if loss == "workspace_removal":
            changed = admin.delete(f"{workspace_path}/members/{user_id}")
        elif loss == "workspace_demotion":
            changed = admin.put(f"{workspace_path}/members/{user_id}", json={"role": "viewer"})
        elif loss == "org_removal":
            changed = admin.delete(f"{org_path}/users/{user_id}")
        elif loss == "logout":
            changed = member.post("/api/v1/auth/logout")
        elif loss == "end":
            changed = member.delete(f"{workspace_path}/playground-session")
        else:
            changed = admin.delete(f"/api/v1/management-keys/{key_id}")
        changed.raise_for_status()
        wait_for_status(inference, 401)
        assert stack.request().status_code == 200
        if loss.startswith("workspace") or loss == "org_removal":
            admin.put(f"{org_path}/users/{user_id}", json={"role": "member"}).raise_for_status()
            admin.put(f"{workspace_path}/members/{user_id}", json={"role": "admin"}).raise_for_status()
            assert inference().status_code == 401
            member.put(f"{workspace_path}/playground-session").raise_for_status()
            assert member.cookies["airllm_playground"] != cookie
            wait_for_status(inference, 401)
