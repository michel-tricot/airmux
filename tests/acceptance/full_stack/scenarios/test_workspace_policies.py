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
            json={"name": name, "definition": {"target": {"kind": "workspace"}, "rule_ids": [rule_id]}},
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
        output_limit_rule_id = _create_rule(
            admin,
            rules_path,
            "Output token ceiling",
            {"kind": "all_requests"},
            {"kind": "request_limits", "max_output_tokens": 1},
        )
        _create_policy(admin, policies_path, "Output token ceiling", output_limit_rule_id)
        assert _poll(
            lambda: (
                httpx.post(
                    f"{stack.dp_url}/inf/v1/chat/completions",
                    headers={"authorization": f"Bearer {stack.caller_api_key}"},
                    json={"model": MODEL, "messages": [{"role": "user", "content": "limited"}], "max_tokens": 2},
                    timeout=10,
                ).status_code
                == 403
            ),
            30,
        ), "the running gateway did not enforce the published output limit"
        enabled = _payload(admin.patch(f"{policies_path}/{policy['id']}", json={"enabled": True}))
        assert enabled["enabled"] is True
        assert _poll(lambda: stack.request().status_code == 403, 30)
        _payload(admin.delete(f"{policies_path}/{policy['id']}"))
        assert _poll(lambda: stack.request().status_code == 200, 30), "deletion did not publish"


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


@pytest.mark.parametrize("stream", [False, True])
def test_user_targets_cover_keys_and_playground_after_bundle_adoption(stack: Stack, stream: bool) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    headers = {"X-Requested-With": "XMLHttpRequest"}
    with httpx.Client(base_url=stack.cp_url, headers=headers, timeout=10) as admin:
        _payload(admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}))
        user_id = _payload(admin.get("/api/v1/auth/me"))["user_id"]
        workspace = _payload(admin.get(f"/api/v1/organizations/{stack.org_id}/workspaces"))[0]
        base = f"/api/v1/organizations/{stack.org_id}/workspaces/{workspace['id']}"
        first = _payload(admin.get(f"{base}/inference-keys"))[0]
        second = _payload(admin.post(f"{base}/inference-keys", json={"label": "Second"}))
        _payload(admin.put(f"{base}/playground-session"))
        sibling = _payload(admin.post(f"/api/v1/organizations/{stack.org_id}/workspaces", json={"name": "Development"}))
        sibling_key = _payload(
            admin.post(f"/api/v1/organizations/{stack.org_id}/workspaces/{sibling['id']}/inference-keys", json={"label": "Development"})
        )
        rule_id = _create_rule(
            admin, f"{base}/rules", "User output limit", {"kind": "all_requests"}, {"kind": "request_limits", "max_output_tokens": 1024}
        )
        user_policy = _payload(
            admin.post(
                f"{base}/policies",
                json={"name": "Principal", "definition": {"target": {"kind": "selected_users", "user_ids": [user_id]}, "rule_ids": [rule_id]}},
            )
        )

        def completion(token: str | None, max_output_tokens: int) -> httpx.Response:
            authentication = (
                {"authorization": f"Bearer {token}"}
                if token is not None
                else {**headers, "Cookie": f"airmux_playground={admin.cookies.get('airmux_playground')}"}
            )
            return httpx.post(
                f"{stack.dp_url}/inf/v1/chat/completions",
                headers=authentication,
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_output_tokens": max_output_tokens,
                    "stream": stream,
                },
                timeout=10,
            )

        assert _poll(lambda: all(completion(token, 1025).status_code == 403 for token in (stack.caller_api_key, second["token"], None)), 30)
        assert completion(second["token"], 1024).status_code == 200
        assert completion(None, 1024).status_code == 200
        assert completion(sibling_key["token"], 1025).status_code == 200
        workspace_rule = _create_rule(
            admin, f"{base}/rules", "Workspace output limit", {"kind": "all_requests"}, {"kind": "request_limits", "max_output_tokens": 4096}
        )
        _create_policy(admin, f"{base}/policies", "Workspace", workspace_rule)
        key_rule = _create_rule(
            admin, f"{base}/rules", "Key output limit", {"kind": "all_requests"}, {"kind": "request_limits", "max_output_tokens": 512}
        )
        _payload(
            admin.post(
                f"{base}/policies",
                json={"name": "Key", "definition": {"target": {"kind": "selected_keys", "key_ids": [first["id"]]}, "rule_ids": [key_rule]}},
            )
        )
        assert _poll(lambda: completion(stack.caller_api_key, 513).status_code == 403, 30)
        assert completion(stack.caller_api_key, 512).status_code == 200
        _payload(admin.patch(f"{base}/policies/{user_policy['id']}", json={"enabled": False}))
        future = _payload(admin.post(f"{base}/inference-keys", json={"label": "Future"}))
        assert _poll(lambda: completion(future["token"], 4097).status_code == 403, 30)
        assert completion(future["token"], 4096).status_code == 200
        assert completion(None, 4097).status_code == 403
