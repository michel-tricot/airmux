from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, MODEL
from test_playground_revocation import wait_for_status

if TYPE_CHECKING:
    from conftest import Stack


def test_password_change_recovers_browser_and_playground_access(stack: Stack) -> None:
    stack.write_config(poll_interval_s=1)
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    csrf = {"X-Requested-With": "XMLHttpRequest"}
    with (
        httpx.Client(base_url=stack.cp_url, headers=csrf, timeout=10.0) as current,
        httpx.Client(base_url=stack.cp_url, headers=csrf, timeout=10.0) as other,
    ):
        for browser in (current, other):
            browser.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).raise_for_status()
        original_cookie = current.cookies["airllm_session"]
        workspace_id = current.get(f"/api/v1/orgs/{stack.org_id}/workspaces").json()["data"][0]["id"]
        path = f"/api/v1/orgs/{stack.org_id}/workspaces/{workspace_id}/playground-session"
        other.put(path).raise_for_status()
        cookie = other.cookies["airllm_playground"]

        def inference() -> httpx.Response:
            return httpx.post(
                f"{stack.dp_url}/inf/v1/chat/completions",
                headers={**csrf, "cookie": f"airllm_playground={cookie}"},
                json={"model": MODEL, "messages": [{"role": "user", "content": "session recovery"}]},
                timeout=2.0,
            )

        wait_for_status(inference, 200)
        changed = current.post("/api/v1/auth/password", json={"current_password": ADMIN_PASSWORD, "new_password": "new-acceptance-password"})
        changed.raise_for_status()
        assert current.cookies["airllm_session"] != original_cookie
        assert current.get("/api/v1/auth/me").status_code == 200
        assert other.get("/api/v1/auth/me").status_code == 401
        wait_for_status(inference, 401)
        assert stack.request().status_code == 200
        assert other.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).status_code == 401
        other.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "new-acceptance-password"}).raise_for_status()
