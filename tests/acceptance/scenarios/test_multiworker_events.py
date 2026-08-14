"""Acceptance: many uvicorn workers share one cache dir and lose no events.

Every successful request must land in the control plane exactly once: distinct event_id count
equal to the number of 200s, with no duplicates and no loss. This is the proof the shared
cache dir works.
"""

from __future__ import annotations

import contextlib
import threading
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from conftest import Stack

WORKERS = 4
CONCURRENCY = 16
PER_CLIENT = 30


def _load(url: str, headers: dict[str, str], body: dict, clients: int, per_client: int) -> int:
    oks: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        served = 0
        with httpx.Client(timeout=30.0) as client:
            for _ in range(per_client):
                # a worker still booting can reset a connection before handling it, recording nothing
                with contextlib.suppress(httpx.HTTPError):
                    served += client.post(url, headers=headers, json=body).status_code == 200
        with lock:
            oks.append(served)

    threads = [threading.Thread(target=worker) for _ in range(clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return sum(oks)


def test_multiworker_shared_cache_dir_loses_no_events(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp(workers=WORKERS)
    stack.wait_dp_ready()
    time.sleep(3)  # wait_dp_ready only proves one worker answered; let the rest boot and poll a bundle

    url = f"{stack.dp_url}/v1/chat/completions"
    headers = {"authorization": f"Bearer {stack.caller_api_key}"}
    body = {"model": "echo", "messages": [{"role": "user", "content": "hi"}]}

    warmup = _load(url, headers, body, clients=WORKERS, per_client=5)
    ok = warmup + _load(url, headers, body, clients=CONCURRENCY, per_client=PER_CLIENT)
    assert ok > 400  # substantial concurrent load actually served across the workers

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and len(stack.events()) < ok:
        time.sleep(0.5)

    events = stack.events()
    ids = {e["event_id"] for e in events}
    assert len(ids) == ok  # no loss: every served request produced a distinct event
    assert len(events) == ok  # exactly once: no duplicates
