from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import httpx
import yaml
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD

if TYPE_CHECKING:
    from stack_harness import Stack


def test_authentication_throttles_without_starving_health_or_inference(stack: Stack) -> None:
    stack.write_config()
    configuration = yaml.safe_load(stack.config_path.read_text())
    configuration["control_plane"]["throttling"] = {
        "authentication": {"burst": 4, "per_second": 2},
        "account": {"burst": 4, "per_second": 2},
        "cli": {"burst": 2, "per_second": 1},
    }
    stack.config_path.write_text(yaml.safe_dump(configuration))
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()

    async def burst() -> list[httpx.Response]:
        async with httpx.AsyncClient(base_url=stack.cp_url, timeout=10) as client:
            return await asyncio.gather(
                *(client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-password"}) for _ in range(16)),
                client.get("/healthz"),
                client.post(
                    stack.dp_url + "/inf/v1/chat/completions",
                    headers={"Authorization": f"Bearer {stack.caller_api_key}"},
                    json={"model": "echo", "messages": [{"role": "user", "content": "during authentication burst"}]},
                ),
            )

    responses = asyncio.run(burst())
    assert [response.status_code for response in responses[-2:]] == [200, 200]
    assert {response.status_code for response in responses[:-2]} <= {401, 429}
    limited = [response for response in responses[:-2] if response.status_code == 429]
    assert limited
    assert all(int(response.headers["Retry-After"]) > 0 for response in limited)

    async def start_burst() -> list[httpx.Response]:
        async with httpx.AsyncClient(base_url=stack.cp_url, timeout=10) as client:
            return await asyncio.gather(*(client.post("/api/v1/auth/cli/start", json={"client_name": "throttle-test"}) for _ in range(5)))

    starts = asyncio.run(start_burst())
    assert any(response.status_code == 200 for response in starts)
    assert any(response.status_code == 429 for response in starts)

    time.sleep(max(int(response.headers["Retry-After"]) for response in limited))
    with httpx.Client(base_url=stack.cp_url, timeout=10) as client:
        login = client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert login.status_code == 200, login.text
