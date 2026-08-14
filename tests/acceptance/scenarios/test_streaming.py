"""Acceptance: streaming per INTERFACE.md, and the accounting when a client hangs up.

A full stream delivers typed delta frames, one closing chunk carrying finish_reason, usage and
gateway, then [DONE]. A client that disconnects mid-stream still produces a usage event: status
cancelled, partial output counted as an estimate. Step 4 of notes/design/DATAPLANE.md."""

from __future__ import annotations

import contextlib
import json
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterator

    from conftest import Stack


@contextlib.contextmanager
def _stream_request(stack: Stack) -> Iterator[httpx.Response]:
    with (
        httpx.Client(timeout=30.0) as client,
        client.stream(
            "POST",
            f"{stack.dp_url}/v1/chat/completions",
            headers={"authorization": f"Bearer {stack.caller_api_key}"},
            json={"model": "echo", "messages": [{"role": "user", "content": "go"}], "stream": True},
        ) as response,
    ):
        yield response


def _events_until(stack: Stack, predicate, timeout: float = 30.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = stack.events()
        if predicate(events):
            return events
        time.sleep(0.5)
    return stack.events()


def test_streamed_completion_and_disconnect_accounting(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()

    with _stream_request(stack) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    lines = [line for line in body.splitlines() if line.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    frames = [json.loads(line[6:]) for line in lines[:-1]]
    text = "".join(f["delta"]["text"] for f in frames if f.get("delta", {}).get("type") == "text")
    assert text == "".join(f"tick{i} " for i in range(30))
    closing = frames[-1]
    assert "delta" not in closing
    assert closing["finish_reason"] == "stop"
    assert closing["usage"]["output_tokens"] == 60
    assert closing["gateway"] == {"adjustments": []}

    ok_events = _events_until(stack, lambda events: any(e["status"] == "ok" and e["stream"] for e in events))
    assert any(e["status"] == "ok" and e["stream"] and e["output_tokens"] == 60 for e in ok_events)

    with _stream_request(stack) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                break  # one frame is enough; leaving the context slams the connection shut mid-stream

    cancelled = _events_until(stack, lambda events: any(e["status"] == "cancelled" for e in events))
    (event,) = [e for e in cancelled if e["status"] == "cancelled"]
    assert event["stream"] is True
    assert 0 < event["output_tokens"] < 60  # partial, estimated from what actually streamed
