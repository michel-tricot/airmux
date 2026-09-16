from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import httpx
from stack_harness import _poll

if TYPE_CHECKING:
    from stack_harness import Stack

WORKERS = 4
CONCURRENCY = 16
PER_CLIENT = 8


def test_multiworker_shared_cache_dir_loses_no_events(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp(workers=WORKERS)
    stack.wait_dp_ready()

    def requests(client_id: int) -> None:
        with httpx.Client(base_url=stack.dp_url, headers={"Authorization": f"Bearer {stack.caller_api_key}"}, timeout=30) as client:
            for request_id in range(PER_CLIENT):
                response = client.post(
                    "/inf/v1/chat/completions",
                    json={"model": "echo", "messages": [{"role": "user", "content": f"client {client_id} request {request_id}"}]},
                )
                assert response.status_code == 200, response.text

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as clients:
        tuple(clients.map(requests, range(CONCURRENCY)))
    expected = CONCURRENCY * PER_CLIENT
    assert stack.upstream_requests == expected
    assert _poll(lambda: httpx.get(stack.dp_url + "/healthz").json()["events"]["pending"] == 0, 30)
    events = stack.events()
    assert len(events) == expected
    assert {event["status"] for event in events} == {"ok"}
    assert len({event["event_id"] for event in events}) == expected
    assert len({event["request_id"] for event in events}) == expected
