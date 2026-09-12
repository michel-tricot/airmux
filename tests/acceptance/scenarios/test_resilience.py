from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import httpx
import pytest
import yaml
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, _poll

if TYPE_CHECKING:
    from conftest import Stack

def _start(stack: Stack) -> None:
    stack.write_config()
    configuration = yaml.safe_load(stack.config_path.read_text())
    configuration["control_plane"]["throttling"] = {
        "authentication": {"burst": 100, "per_second": 100},
        "account": {"burst": 100, "per_second": 100},
        "password_workers": 1,
        "password_queue": 2,
    }
    stack.config_path.write_text(yaml.safe_dump(configuration))
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()

def test_bounded_malformed_inputs_and_disconnects_preserve_service_recovery(stack: Stack) -> None:
    _start(stack)
    with httpx.Client(base_url=stack.cp_url, timeout=3) as control, httpx.Client(base_url=stack.dp_url, timeout=3) as inference:
        auth_inputs = [[], {"email": [], "password": "wrong"}, {"email": ADMIN_EMAIL, "password": "x" * 1025}]
        for malformed in auth_inputs:
            response = control.post("/api/v1/auth/login", json=malformed)
            assert response.status_code == 422, response.text
        headers = {"Authorization": f"Bearer {stack.caller_api_key}", "x-airllm-dialect": "canonical"}
        body = {"model": "echo", "messages": [{"role": "user", "content": "hi"}]}
        malformed_parameters = [
            (field, value)
            for field, values in {"messages": [[]], "stream": ["true"], "max_tokens": [0]}.items()
            for value in values
        ]
        baseline = stack.upstream_requests
        for field, value in malformed_parameters:
            response = inference.post("/inf/v1/chat/completions", headers=headers, json={**body, field: value})
            assert response.status_code == 400, response.text
        for malformed_json in (b"{", b"[", b"\xff"):
            response = inference.post("/inf/v1/chat/completions", headers={**headers, "Content-Type": "application/json"}, content=malformed_json)
            assert response.status_code == 400, response.text
        assert stack.upstream_requests == baseline
        response = inference.post(
            "/inf/v1/chat/completions",
            headers=headers,
            json={**body, "messages": [{"role": "user", "content": "malformed-sse-name"}], "stream": True},
        )
        assert response.status_code == 200
        errors = [json.loads(line[6:])["error"] for line in response.text.splitlines() if line.startswith("data: ") and '"error"' in line]
        assert len(errors) == 1
        assert errors[0]["code"] == "invalid_upstream_response"
        assert control.get("/healthz").status_code == 200
        assert control.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).status_code == 200
    asyncio.run(_disconnects(stack))
    assert _poll(lambda: sum(event["status"] == "cancelled" for event in stack.events()) == 1, 10)
    cancelled = [event for event in stack.events() if event["status"] == "cancelled"]
    assert all(event["stream"] and 0 < event["output_tokens"] < 60 for event in cancelled)
    assert any(event["status"] == "upstream_error" for event in stack.events())
    assert stack.request().status_code == 200


async def _disconnects(stack: Stack) -> None:
    async with httpx.AsyncClient(base_url=stack.dp_url, timeout=3) as client, asyncio.timeout(5):

        async def disconnect() -> None:
            async with client.stream(
                "POST",
                "/inf/v1/chat/completions",
                headers={"Authorization": f"Bearer {stack.caller_api_key}"},
                json={"model": "echo", "messages": [{"role": "user", "content": "disconnect"}], "stream": True},
            ) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and '"delta"' in line:
                        return
                pytest.fail("stream ended before a content delta")

        await disconnect()
