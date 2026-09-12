from __future__ import annotations

import asyncio
import json
import math
import time
from typing import TYPE_CHECKING

import httpx
import pytest
import yaml
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, _poll

if TYPE_CHECKING:
    from conftest import Stack

CONCURRENCY = 6
ATTEMPTS_PER_CLIENT = 20
ATTEMPT_INTERVAL_S = 0.15
PROBES = 20
LIMIT_BURST = 4
LIMIT_RATE = 2


def _start(stack: Stack, *, authentication_burst: int = LIMIT_BURST) -> None:
    stack.write_config()
    configuration = yaml.safe_load(stack.config_path.read_text())
    configuration["control_plane"]["throttling"] = {
        "authentication": {"burst": authentication_burst, "per_second": LIMIT_RATE},
        "account": {"burst": 100, "per_second": 100},
        "password_workers": 1,
        "password_queue": 2,
    }
    stack.config_path.write_text(yaml.safe_dump(configuration))
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()


async def _load(stack: Stack) -> tuple[list[httpx.Response], list[float], float]:
    async with (
        httpx.AsyncClient(base_url=stack.cp_url, timeout=3) as control,
        httpx.AsyncClient(base_url=stack.dp_url, timeout=3) as inference,
        asyncio.timeout(15),
    ):

        async def attempts() -> list[httpx.Response]:
            responses = []
            for _ in range(ATTEMPTS_PER_CLIENT):
                responses.append(await control.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "incorrect-password"}))
                await asyncio.sleep(ATTEMPT_INTERVAL_S)
            return responses

        async def probes() -> list[float]:
            latencies = []
            for _ in range(PROBES):
                started = time.monotonic()
                health, completion = await asyncio.gather(
                    control.get("/healthz"),
                    inference.post(
                        "/inf/v1/chat/completions",
                        headers={"Authorization": f"Bearer {stack.caller_api_key}"},
                        json={"model": "echo", "messages": [{"role": "user", "content": "health during load"}]},
                    ),
                )
                latencies.append(time.monotonic() - started)
                assert health.status_code == 200
                assert completion.status_code == 200, completion.text
                await asyncio.sleep(0.1)
            return latencies

        started = time.monotonic()
        workers = [asyncio.create_task(attempts()) for _ in range(CONCURRENCY)]
        monitor = asyncio.create_task(probes())
        results = await asyncio.gather(*workers)
        latencies = await monitor
        return [response for responses in results for response in responses], latencies, time.monotonic() - started


def test_sustained_authentication_load_preserves_health_inference_and_recovers(stack: Stack) -> None:
    _start(stack)
    responses, latencies, duration = asyncio.run(_load(stack))
    assert len(responses) == CONCURRENCY * ATTEMPTS_PER_CLIENT
    assert duration >= ATTEMPTS_PER_CLIENT * ATTEMPT_INTERVAL_S
    assert {response.status_code for response in responses} <= {401, 429, 503}
    assert sum(response.status_code == 401 for response in responses) <= LIMIT_BURST + math.ceil(duration * LIMIT_RATE)
    assert any(response.status_code == 401 for response in responses)
    denied = [response for response in responses if response.status_code in {429, 503}]
    assert len(denied) > len(responses) // 2
    assert all(0 < int(response.headers["Retry-After"]) <= 2 for response in denied)
    assert all(response.headers["Cache-Control"] == "no-store" for response in denied)
    assert max(latencies) < 3
    time.sleep(max(int(response.headers["Retry-After"]) for response in denied))
    with httpx.Client(base_url=stack.cp_url, timeout=3) as client:
        recovery = client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert recovery.status_code == 200, recovery.text
    assert stack.request().status_code == 200


def test_bounded_malformed_inputs_and_disconnects_preserve_service_recovery(stack: Stack) -> None:
    _start(stack, authentication_burst=100)
    with httpx.Client(base_url=stack.cp_url, timeout=3) as control, httpx.Client(base_url=stack.dp_url, timeout=3) as inference:
        auth_inputs = [[], None, 1, "bad", {}, {"email": [], "password": "wrong"}, {"email": ADMIN_EMAIL, "password": "x" * 1025}]
        for malformed in auth_inputs:
            response = control.post("/api/v1/auth/login", json=malformed)
            assert response.status_code == 422, response.text
        headers = {"Authorization": f"Bearer {stack.caller_api_key}", "x-airllm-dialect": "canonical"}
        body = {"model": "echo", "messages": [{"role": "user", "content": "hi"}]}
        malformed_parameters = [
            (field, value)
            for field, values in {"messages": [[], None, 1, "bad"], "stream": [0, "true", [], {}], "max_tokens": [0, -1, [], {}]}.items()
            for value in values
        ]
        baseline = stack.upstream_requests
        for field, value in malformed_parameters:
            response = inference.post("/inf/v1/chat/completions", headers=headers, json={**body, field: value})
            assert response.status_code == 400, response.text
        for malformed_json in (b"{", b"[", b"\xff", b'{"model":' + b"[" * 32):
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
    assert _poll(lambda: sum(event["status"] == "cancelled" for event in stack.events()) == 4, 10)
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

        await asyncio.gather(*(disconnect() for _ in range(4)))
