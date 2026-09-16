from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import httpx
import yaml
from stack_harness import _poll, metric

if TYPE_CHECKING:
    from stack_harness import Stack

REQUESTS = 50


class EventProxy(ThreadingHTTPServer):
    def __init__(self, destination: str) -> None:
        super().__init__(("127.0.0.1", 0), EventProxyHandler)
        self.destination = destination
        self.deliveries: list[list[str]] = []
        self.committed = threading.Event()
        self.release = threading.Event()
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()


class EventProxyHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        proxy = self.server
        assert isinstance(proxy, EventProxy)
        assert self.path == "/api/v1/events"
        body = self.rfile.read(int(self.headers["content-length"]))
        try:
            response = httpx.post(
                proxy.destination + self.path,
                content=body,
                headers={"Authorization": self.headers["authorization"], "Content-Type": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            status = 503
        else:
            proxy.deliveries.append([event["event_id"] for event in json.loads(body)])
            status = response.status_code
            if len(proxy.deliveries) == 1:
                proxy.committed.set()
                proxy.release.wait(timeout=15)
                status = 503
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 parameter name is required by BaseHTTPRequestHandler
        return


def test_buffered_events_retry_after_a_lost_acknowledgement_without_duplicates(stack: Stack) -> None:
    proxy = EventProxy(stack.cp_url)
    try:
        stack.write_config()
        configuration = yaml.safe_load(stack.config_path.read_text())
        configuration["data_plane"]["events"]["control_plane"]["url"] = f"http://127.0.0.1:{proxy.server_port}"
        stack.config_path.write_text(yaml.safe_dump(configuration))
        stack.start_cp()
        stack.collect_credentials()
        stack.start_dp()
        stack.wait_dp_ready()
        stack.stop("cp")
        for _ in range(REQUESTS):
            assert stack.request().status_code == 200
        assert metric(stack.dp_url + "/metrics", "airmux_data_plane_metering_outbox_pending") == REQUESTS

        stack.start_cp()
        assert proxy.committed.wait(timeout=15), "no event batch committed after the control plane restarted"
        events = stack.events()
        event_ids = {event["event_id"] for event in events}
        assert len(events) == len(event_ids) == REQUESTS
        assert metric(stack.dp_url + "/metrics", "airmux_data_plane_metering_outbox_pending") == REQUESTS
        proxy.release.set()
        assert _poll(lambda: metric(stack.dp_url + "/metrics", "airmux_data_plane_metering_outbox_pending") == 0, 15)
        assert len(proxy.deliveries) == 2
        assert proxy.deliveries[0] == proxy.deliveries[1]
        assert set(proxy.deliveries[0]) == event_ids
        assert len(stack.events()) == REQUESTS
        assert {event["event_id"] for event in stack.events()} == event_ids
    finally:
        proxy.release.set()
        stack.stop("dp")
        proxy.shutdown()
        proxy.server_close()
        proxy.thread.join(timeout=5)
