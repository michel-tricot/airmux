from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD, _payload, _poll

if TYPE_CHECKING:
    from stack_harness import Stack


def test_output_token_alias_cannot_bypass_live_policy(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10) as admin:
        _payload(admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}))
        workspace = _payload(admin.get(f"/api/v1/organizations/{stack.org_id}/workspaces"))[0]
        scope = f"/api/v1/organizations/{stack.org_id}/workspaces/{workspace['id']}"
        rule = _payload(
            admin.post(
                f"{scope}/rules",
                json={
                    "name": "One output token",
                    "definition": {"match": {"kind": "all_requests"}, "action": {"kind": "request_limits", "max_output_tokens": 1}},
                },
            )
        )
        _payload(
            admin.post(
                f"{scope}/policies",
                json={"name": "One output token", "definition": {"target": {"kind": "workspace"}, "rule_ids": [rule["id"]]}},
            )
        )
    body = {"model": "quirk", "messages": [{"role": "user", "content": "hi"}]}
    headers = {"authorization": f"Bearer {stack.caller_api_key}", "x-tokkeeper-dialect": "canonical"}
    with httpx.Client(base_url=stack.dp_url, headers=headers, timeout=10) as client:
        path = "/inf/v1/chat/completions"
        assert _poll(lambda: client.post(path, json={**body, "max_tokens": 999}).status_code == 403, 30)
        baseline = stack.upstream_requests
        response = client.post(path, json={**body, "max_completion_tokens": 999})
        assert response.status_code == 400, response.text
        response = client.post(path, headers={"x-tokkeeper-dialect": "openai_native"}, json={**body, "max_completion_tokens": 999})
        assert response.status_code == 403, response.text
        assert stack.upstream_requests == baseline
        response = client.post(path, json={**body, "max_tokens": 1})
        assert response.status_code == 200, response.text
        sent = json.loads(response.json()["content"][0]["text"])
        assert sent["max_completion_tokens"] == 1
        assert "max_tokens" not in sent
