from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx
import yaml
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD

if TYPE_CHECKING:
    from stack_harness import Stack


def test_malformed_authentication_and_password_overload_preserve_service_recovery(stack: Stack) -> None:
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
    with httpx.Client(base_url=stack.cp_url, timeout=10) as control:
        for malformed in [[], {"email": [], "password": "wrong"}, {"email": ADMIN_EMAIL, "password": "x" * 1025}]:
            response = control.post("/api/v1/auth/login", json=malformed)
            assert response.status_code == 422, response.text

    async def burst() -> list[httpx.Response]:
        async with httpx.AsyncClient(base_url=stack.cp_url, timeout=10) as client:
            return await asyncio.gather(
                *(client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-password"}) for _ in range(16)),
                client.get("/healthz"),
                client.post(
                    stack.dp_url + "/inf/v1/chat/completions",
                    headers={"Authorization": f"Bearer {stack.caller_api_key}"},
                    json={"model": "echo", "messages": [{"role": "user", "content": "during password overload"}]},
                ),
            )

    responses = asyncio.run(burst())
    assert [response.status_code for response in responses[-2:]] == [200, 200]
    assert {response.status_code for response in responses[:-2]} == {401, 503}
    overloaded = [response for response in responses[:-2] if response.status_code == 503]
    assert all(response.json() == {"detail": "Authentication service is busy"} for response in overloaded)
    assert all(int(response.headers["Retry-After"]) > 0 for response in overloaded)
    with httpx.Client(base_url=stack.cp_url, timeout=10) as control:
        response = control.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert response.status_code == 200, response.text
    assert stack.request().status_code == 200
