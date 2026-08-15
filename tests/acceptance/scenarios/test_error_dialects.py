from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from conftest import Stack


def test_upstream_errors_return_in_the_callers_dialect(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()

    for stream in (False, True):
        response = httpx.post(
            f"{stack.dp_url}/v1/messages",
            headers={"authorization": f"Bearer {stack.caller_api_key}"},
            json={"model": "echo", "max_tokens": 8, "messages": [{"role": "user", "content": "rate-limited"}], "stream": stream},
            timeout=10.0,
        )
        assert response.status_code == 429
        assert response.json() == {"type": "error", "error": {"type": "rate_limit_exceeded", "message": "slow down"}}

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and sum(event["status"] == "rate_limited" for event in stack.events()) < 2:
        time.sleep(0.5)
    assert sum(event["status"] == "rate_limited" for event in stack.events()) == 2
