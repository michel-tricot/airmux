from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, MODEL, _payload, _poll

if TYPE_CHECKING:
    from conftest import Stack


def test_policy_changes_reach_running_gateway_and_preserve_workspace_scope(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    assert stack.request().status_code == 200

    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10.0) as admin:
        _payload(admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}))
        workspace = _payload(admin.get(f"/api/v1/orgs/{stack.org_id}/workspaces"))[0]
        path = f"/api/v1/orgs/{stack.org_id}/workspaces/{workspace['id']}/policies"
        sibling = _payload(admin.post(f"/api/v1/orgs/{stack.org_id}/workspaces", json={"name": "sibling"}))
        caller = _payload(admin.post(f"/api/v1/orgs/{stack.org_id}/workspaces/{sibling['id']}/inference-keys", json={"label": "sibling"}))
        policy = _payload(
            admin.post(
                path,
                json={
                    "name": "Only the other model",
                    "definition": {
                        "target": {"kind": "all_keys"},
                        "rules": [{"match": {"kind": "all_requests"}, "action": {"kind": "models", "names": ["quirk"]}}],
                    },
                },
            )
        )
        assert _poll(lambda: stack.request().status_code == 403, 30), "the running gateway did not enforce the published policy"
        response = httpx.post(
            f"{stack.dp_url}/inf/v1/chat/completions",
            headers={"authorization": f"Bearer {caller['token']}"},
            json={"model": MODEL, "messages": [{"role": "user", "content": "sibling"}]},
            timeout=10,
        )
        assert response.status_code == 200
        _payload(admin.patch(f"{path}/{policy['id']}", json={"enabled": False}))
        assert _poll(lambda: stack.request().status_code == 200, 30), "disabling the policy was not published"
        _payload(
            admin.post(
                path,
                json={
                    "name": "Budget preview",
                    "definition": {
                        "target": {"kind": "all_keys"},
                        "rules": [
                            {
                                "match": {"kind": "all_requests"},
                                "action": {"kind": "budget", "period": "day", "amount_usd": "0.000001", "sharing": "shared"},
                            }
                        ],
                    },
                },
            )
        )
        enabled = _payload(admin.patch(f"{path}/{policy['id']}", json={"enabled": True}))
        assert enabled["enabled"] is True
        assert _poll(lambda: stack.request().status_code == 403, 30)
        _payload(admin.delete(f"{path}/{policy['id']}"))
        assert _poll(lambda: stack.request().status_code == 200, 30), "deletion did not publish, or the budget policy enforced"


@pytest.mark.parametrize("stream", [False, True])
def test_fallback_runs_through_real_gateway_and_stays_inside_restrictions(stack: Stack, stream: bool) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10.0) as admin:
        _payload(admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}))
        workspace = _payload(admin.get(f"/api/v1/orgs/{stack.org_id}/workspaces"))[0]
        path = f"/api/v1/orgs/{stack.org_id}/workspaces/{workspace['id']}/policies"
        _payload(
            admin.post(
                path,
                json={
                    "name": "Use the backup on unavailable",
                    "definition": {
                        "target": {"kind": "all_keys"},
                        "rules": [
                            {
                                "match": {"kind": "all_requests"},
                                "action": {
                                    "kind": "fallback",
                                    "models": ["quirk"],
                                    "on": ["upstream_unavailable"],
                                    "max_attempts": 2,
                                    "timeout_ms": 10000,
                                },
                            }
                        ],
                    },
                },
            )
        )

        def completion() -> httpx.Response:
            return httpx.post(
                f"{stack.dp_url}/inf/v1/chat/completions",
                headers={"authorization": f"Bearer {stack.caller_api_key}"},
                json={"model": MODEL, "messages": [{"role": "user", "content": "fallback-primary-unavailable"}], "stream": stream},
                timeout=15,
            )

        assert _poll(lambda: completion().status_code == 200 and any(event["model_id"] == "quirk" for event in stack.events()), 30)
        _payload(
            admin.post(
                path,
                json={
                    "name": "Forbid the backup provider",
                    "definition": {
                        "target": {"kind": "all_keys"},
                        "rules": [{"match": {"kind": "request", "models": [MODEL]}, "action": {"kind": "providers", "names": ["stub"]}}],
                    },
                },
            )
        )
        assert _poll(lambda: completion().status_code == 503, 30), "fallback bypassed the original request's provider restriction"
