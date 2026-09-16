from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD, MODEL

if TYPE_CHECKING:
    from collections.abc import Callable

    from stack_harness import Stack


def _wait(predicate: Callable[[], bool], timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.25)
    return False


def test_new_inference_key_reaches_a_running_data_plane_without_manual_publication(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()

    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10.0) as admin:
        login = admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        login.raise_for_status()
        org_id = login.json()["data"]["orgs"][0]
        workspaces = admin.get(f"/api/v1/organizations/{org_id}/workspaces")
        workspaces.raise_for_status()
        workspace_id = workspaces.json()["data"][0]["id"]
        inference_key_response = admin.post(
            f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys",
            json={"label": "automatic-publication"},
        )
        inference_key_response.raise_for_status()
        token = inference_key_response.json()["data"]["token"]

    def accepted() -> bool:
        response = httpx.post(
            f"{stack.dp_url}/inf/v1/chat/completions",
            headers={"authorization": f"Bearer {token}"},
            json={"model": MODEL, "messages": [{"role": "user", "content": "new key"}]},
            timeout=10.0,
        )
        return response.status_code == 200

    assert _wait(accepted), "the running data plane never adopted the automatically published key"
