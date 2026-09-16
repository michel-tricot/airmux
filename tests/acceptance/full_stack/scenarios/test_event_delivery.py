from __future__ import annotations

import json
from collections import Counter
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
import pytest
from stack_harness import _poll

if TYPE_CHECKING:
    from stack_harness import Stack


def test_success_disconnect_and_provider_failures_reach_the_control_plane(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    request_ids: list[str] = []
    with httpx.Client(base_url=stack.dp_url, headers={"Authorization": f"Bearer {stack.caller_api_key}"}, timeout=30) as client:
        body = {"model": "echo", "messages": [{"role": "user", "content": "go"}], "stream": True}
        response = client.post("/inf/v1/chat/completions", json=body)
        assert response.status_code == 200
        request_ids.append(response.headers["x-request-id"])
        assert "tick29" in response.text
        with client.stream("POST", "/inf/v1/chat/completions", json=body) as response:
            assert response.status_code == 200
            request_ids.append(response.headers["x-request-id"])
            for line in response.iter_lines():
                if line == "data: [DONE]" or not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if any(choice.get("delta", {}).get("content") for choice in event.get("choices", [])):
                    break
            else:
                pytest.fail("stream ended before delivering content")
        for prompt, status in [("rate-limited", 429), ("malformed-buffered", 502)]:
            response = stack.request(prompt)
            assert response.status_code == status, response.text
            request_ids.append(response.headers["x-request-id"])
    assert _poll(lambda: httpx.get(stack.dp_url + "/healthz").json()["events"]["pending"] == 0 and len(stack.events()) == 4, 15)
    events = stack.events()
    assert Counter(event["status"] for event in events) == Counter({"ok": 1, "cancelled": 1, "rate_limited": 1, "upstream_error": 1})
    assert {event["request_id"] for event in events} == set(request_ids)
    assert len({event["event_id"] for event in events}) == 4
    assert all(UUID(event["event_id"]).version == 7 for event in events)
    (successful,) = [event for event in events if event["status"] == "ok"]
    assert successful["stream"] is True
    assert (successful["input_tokens"], successful["output_tokens"]) == (11, 60)
    (cancelled,) = [event for event in events if event["status"] == "cancelled"]
    assert cancelled["stream"] is True
    assert 0 < cancelled["output_tokens"] < 60
    assert all(event["output_tokens"] == 0 for event in events if event["status"] in {"rate_limited", "upstream_error"})
