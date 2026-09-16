from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD, MODEL, _payload, _poll

if TYPE_CHECKING:
    from stack_harness import Stack


def test_workspace_offboarding_revokes_the_existing_data_plane_credential(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()

    def completion() -> httpx.Response:
        return httpx.post(
            f"{stack.dp_url}/inf/v1/chat/completions",
            headers={"authorization": f"Bearer {stack.caller_api_key}"},
            json={"model": MODEL, "messages": [{"role": "user", "content": "offboarding"}]},
            timeout=10,
        )

    assert completion().status_code == 200
    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10) as admin:
        _payload(admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}))
        user_id = _payload(admin.get("/api/v1/auth/me"))["user_id"]
        workspace = _payload(admin.get(f"/api/v1/organizations/{stack.org_id}/workspaces"))[0]
        _payload(admin.delete(f"/api/v1/organizations/{stack.org_id}/workspaces/{workspace['id']}/members/{user_id}"))

    assert _poll(lambda: completion().status_code == 401, 30), "the replacement bundle did not revoke the offboarded credential"
