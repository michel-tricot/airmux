"""Acceptance: many uvicorn workers share one cache dir without losing or duplicating events.

Every request received by the upstream must land exactly once in the control plane. The upstream
count remains observable when the gateway served a request but its response was lost in transit.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import Counter
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from stack_harness import Stack

WORKERS = 4
CONCURRENCY = 16
PER_CLIENT = 30


def _load(url: str, headers: dict[str, str], body: dict, clients: int, per_client: int) -> int:
    successes: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        served = 0
        with httpx.Client(timeout=30.0) as client:
            for _ in range(per_client):
                with contextlib.suppress(httpx.HTTPError):
                    response = client.post(url, headers=headers, json=body)
                    if response.status_code == 200:
                        served += 1
        with lock:
            successes.append(served)

    threads = [threading.Thread(target=worker) for _ in range(clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return sum(successes)


def test_multiworker_shared_cache_dir_loses_no_events(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp(workers=WORKERS)
    stack.wait_dp_ready()
    time.sleep(3)  # wait_dp_ready only proves one worker answered; let the rest boot and poll a bundle

    url = f"{stack.dp_url}/inf/v1/chat/completions"
    headers = {"authorization": f"Bearer {stack.caller_api_key}"}
    body = {"model": "echo", "messages": [{"role": "user", "content": "hi"}]}

    successful = _load(url, headers, body, clients=WORKERS, per_client=5)
    successful += _load(url, headers, body, clients=CONCURRENCY, per_client=PER_CLIENT)
    assert successful > 400

    served = stack.upstream_requests
    assert served >= successful

    deadline = time.monotonic() + 30
    events = stack.events()
    while time.monotonic() < deadline and sum(event["status"] == "ok" for event in events) < served:
        time.sleep(0.5)
        events = stack.events()

    event_request_ids = [event["request_id"] for event in events]
    statuses = Counter(str(event["status"]) for event in events)
    assert len(set(event_request_ids)) == len(event_request_ids), f"duplicate request ids: {statuses}"
    assert statuses["ok"] == served, f"upstream requests: {served}; usage events: {statuses}"
