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


def test_configuration_changes_publish_and_reach_a_running_data_plane(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()

    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10.0) as admin:
        login = admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        login.raise_for_status()
        principal = login.json()["data"]
        org_id = principal["orgs"][0]
        workspaces = admin.get(f"/api/v1/organizations/{org_id}/workspaces")
        workspaces.raise_for_status()
        workspace_id = workspaces.json()["data"][0]["id"]
        inference_key_response = admin.post(
            f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys",
            json={"label": "automatic-publication", "user_id": principal["user_id"]},
        )
        inference_key_response.raise_for_status()
        inference_key = inference_key_response.json()["data"]
        token = inference_key["token"]

        def completion(model: str) -> httpx.Response:
            return httpx.post(
                f"{stack.dp_url}/inf/v1/chat/completions",
                headers={"authorization": f"Bearer {token}"},
                json={"model": model, "messages": [{"role": "user", "content": "asynchronous configuration"}]},
                timeout=10.0,
            )

        assert _wait(lambda: completion(MODEL).status_code == 200), "the running data plane never adopted the automatically published key"

        added_model = "added-after-startup"
        taxonomy_response = admin.post(
            "/api/v1/instance/taxonomy/models",
            json={
                "model_id": added_model,
                "provider_id": "stub",
                "upstream_model": MODEL,
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
        )
        taxonomy_response.raise_for_status()
        assert _wait(lambda: completion(added_model).status_code == 200), "the running data plane never admitted the added taxonomy model"

        revoked = admin.delete(f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys/{inference_key['id']}")
        revoked.raise_for_status()
        assert _wait(lambda: completion(MODEL).status_code == 401), "the running data plane never admitted the key revocation"
