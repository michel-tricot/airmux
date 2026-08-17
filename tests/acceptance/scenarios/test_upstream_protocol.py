from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from conftest import Stack


def test_invalid_upstream_successes_are_rejected(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()

    buffered = stack.request("malformed-buffered")
    assert buffered.status_code == 502
    assert buffered.json()["error"]["code"] == "invalid_upstream_response"

    with httpx.stream(
        "POST",
        f"{stack.dp_url}/inf/v1/chat/completions",
        headers={"authorization": f"Bearer {stack.caller_api_key}"},
        json={"model": "echo", "messages": [{"role": "user", "content": "truncated-stream"}], "stream": True},
        timeout=10.0,
    ) as streamed:
        assert streamed.status_code == 200
        body = "".join(streamed.iter_text())
    payloads = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
    errors = [payload["error"] for payload in payloads if "error" in payload]
    assert errors == [{"code": "invalid_upstream_response", "message": "upstream stream ended before its terminal event"}]

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        events = [event for event in stack.events() if event["status"] == "upstream_error"]
        if len(events) == 2:
            break
        time.sleep(0.5)
    assert len(events) == 2
