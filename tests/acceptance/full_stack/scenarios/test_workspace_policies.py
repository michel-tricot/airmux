from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD, MODEL, _payload, _poll

if TYPE_CHECKING:
    from stack_harness import Stack


def _create_rule(admin: httpx.Client, rules_path: str, name: str, match: dict[str, object], action: dict[str, object]) -> str:
    return _payload(admin.post(rules_path, json={"name": name, "definition": {"match": match, "action": action}}))["id"]


def _create_policy(admin: httpx.Client, policies_path: str, name: str, rule_id: str) -> dict[str, object]:
    return _payload(
        admin.post(
            policies_path,
            json={"name": name, "definition": {"target": {"kind": "all_keys"}, "rule_ids": [rule_id]}},
        )
    )


def test_policy_changes_reach_running_gateway_and_preserve_workspace_scope(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    assert stack.request().status_code == 200

    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10.0) as admin:
        _payload(admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}))
        workspace = _payload(admin.get(f"/api/v1/organizations/{stack.org_id}/workspaces"))[0]
        policies_path = f"/api/v1/organizations/{stack.org_id}/workspaces/{workspace['id']}/policies"
        rules_path = f"/api/v1/organizations/{stack.org_id}/workspaces/{workspace['id']}/rules"
        sibling = _payload(admin.post(f"/api/v1/organizations/{stack.org_id}/workspaces", json={"name": "sibling"}))
        caller = _payload(admin.post(f"/api/v1/organizations/{stack.org_id}/workspaces/{sibling['id']}/inference-keys", json={"label": "sibling"}))
        model_rule_id = _create_rule(
            admin,
            rules_path,
            "Only the other model",
            {"kind": "all_requests"},
            {"kind": "models", "names": ["quirk"]},
        )
        policy = _create_policy(admin, policies_path, "Only the other model", model_rule_id)
        assert _poll(lambda: stack.request().status_code == 403, 30), "the running gateway did not enforce the published policy"
        response = httpx.post(
            f"{stack.dp_url}/inf/v1/chat/completions",
            headers={"authorization": f"Bearer {caller['token']}"},
            json={"model": MODEL, "messages": [{"role": "user", "content": "sibling"}]},
            timeout=10,
        )
        assert response.status_code == 200
        _payload(admin.patch(f"{policies_path}/{policy['id']}", json={"enabled": False}))
        assert _poll(lambda: stack.request().status_code == 200, 30), "disabling the policy was not published"
        budget_rule_id = _create_rule(
            admin,
            rules_path,
            "Budget preview",
            {"kind": "all_requests"},
            {"kind": "budget", "period": "day", "amount_usd": "0.000001", "sharing": "shared"},
        )
        _create_policy(admin, policies_path, "Budget preview", budget_rule_id)
        enabled = _payload(admin.patch(f"{policies_path}/{policy['id']}", json={"enabled": True}))
        assert enabled["enabled"] is True
        assert _poll(lambda: stack.request().status_code == 403, 30)
        _payload(admin.delete(f"{policies_path}/{policy['id']}"))
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
        workspace = _payload(admin.get(f"/api/v1/organizations/{stack.org_id}/workspaces"))[0]
        policies_path = f"/api/v1/organizations/{stack.org_id}/workspaces/{workspace['id']}/policies"
        rules_path = f"/api/v1/organizations/{stack.org_id}/workspaces/{workspace['id']}/rules"
        fallback_rule_id = _create_rule(
            admin,
            rules_path,
            "Use the backup on unavailable",
            {"kind": "all_requests"},
            {"kind": "fallback", "models": ["quirk"], "on": ["upstream_unavailable"], "max_attempts": 2, "timeout_ms": 10000},
        )
        _create_policy(admin, policies_path, "Use the backup on unavailable", fallback_rule_id)

        def completion() -> httpx.Response:
            return httpx.post(
                f"{stack.dp_url}/inf/v1/chat/completions",
                headers={"authorization": f"Bearer {stack.caller_api_key}"},
                json={"model": MODEL, "messages": [{"role": "user", "content": "fallback-primary-unavailable"}], "stream": stream},
                timeout=15,
            )

        assert _poll(lambda: completion().status_code == 200 and any(event["model_id"] == "quirk" for event in stack.events()), 30)
        provider_rule_id = _create_rule(
            admin,
            rules_path,
            "Forbid the backup provider",
            {"kind": "request", "models": [MODEL]},
            {"kind": "providers", "names": ["stub"]},
        )
        _create_policy(admin, policies_path, "Forbid the backup provider", provider_rule_id)
        assert _poll(lambda: completion().status_code == 503, 30), "fallback bypassed the original request's provider restriction"
