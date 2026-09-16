from __future__ import annotations

import json
import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from http.client import HTTPResponse
from typing import TYPE_CHECKING

import httpx
from stack_harness import STUB_API_KEY, _poll, _StubServer

if TYPE_CHECKING:
    from pathlib import Path

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
            assert _poll(lambda: client.get("/readyz").status_code == 200, 60), "selected data plane worker never served a bundle"
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


def test_upstream_accepts_a_full_concurrent_connection_burst(tmp_path: Path) -> None:
    body = json.dumps({"model": "echo", "messages": [{"role": "user", "content": "hi"}]}).encode()
    request = (
        f"POST /chat/completions HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {STUB_API_KEY}\r\n"
        f"Content-Length: {len(body)}\r\nContent-Type: application/json\r\n\r\n"
    ).encode() + body
    with _StubServer(("127.0.0.1", 0), tmp_path / "upstream.log") as upstream, ExitStack() as connections:
        clients = [connections.enter_context(socket.create_connection(("127.0.0.1", upstream.server_port), timeout=1)) for _ in range(CONCURRENCY)]
        upstream.start()
        try:
            for client in clients:
                client.sendall(request)
                with HTTPResponse(client) as response:
                    response.begin()
                    assert response.status == 200
                    assert json.loads(response.read())["choices"][0]["message"]["content"] == "ok"
            assert upstream.request_count == CONCURRENCY
        finally:
            upstream.shutdown()
