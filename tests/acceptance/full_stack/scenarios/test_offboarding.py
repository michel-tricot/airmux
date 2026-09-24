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
        assert "deleted_at" not in workspace
        assert workspace["created_at"] == workspace["updated_at"]
        workspace_path = f"/api/v1/organizations/{stack.org_id}/workspaces/{workspace['id']}"
        _payload(admin.patch(workspace_path, json={"name": "Renamed"}))
        renamed = _payload(admin.get(workspace_path))
        assert renamed["name"] == "Renamed"
        assert "deleted_at" not in renamed
        assert renamed["created_at"] == workspace["created_at"]
        assert renamed["updated_at"] > workspace["updated_at"]
        deleted = _payload(admin.delete(f"{workspace_path}/members/{user_id}"))
        assert deleted["id"] == f"{user_id}/{workspace['id']}"
        assert deleted["deleted_at"] is not None
        assert admin.delete(f"{workspace_path}/members/{user_id}").status_code == 404

    assert _poll(lambda: completion().status_code == 401, 30), "the replacement bundle did not revoke the offboarded credential"
