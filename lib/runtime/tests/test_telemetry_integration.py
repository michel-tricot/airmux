from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from queue import Queue
from threading import Thread
from typing import TYPE_CHECKING

import pytest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest

from airmux_runtime.telemetry import MetricsTelemetry

if TYPE_CHECKING:
    from collections.abc import Iterator


class _CollectorHandler(BaseHTTPRequestHandler):
    payloads: Queue[bytes]

    def do_POST(self) -> None:
        self.payloads.put(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 matches BaseHTTPRequestHandler
        pass


@contextmanager
def _collector() -> Iterator[tuple[str, Queue[bytes]]]:
    payloads: Queue[bytes] = Queue()
    _CollectorHandler.payloads = payloads
    server = HTTPServer(("127.0.0.1", 0), _CollectorHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1/metrics", payloads
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.parametrize(("configured_name", "expected_name"), [(None, "default-service"), ("configured-service", "configured-service")])
def test_metrics_export_to_otlp_and_prometheus(monkeypatch, configured_name, expected_name) -> None:
    with _collector() as (endpoint, payloads):
        monkeypatch.setenv("OTEL_METRICS_EXPORTER", "otlp")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", endpoint)
        if configured_name is None:
            monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
        else:
            monkeypatch.setenv("OTEL_SERVICE_NAME", configured_name)
        telemetry = MetricsTelemetry("default-service")
        try:
            counter = telemetry.meter.create_counter("airmux_test_requests")

            counter.add(1, {"outcome": "success"})

            assert 'airmux_test_requests_total{outcome="success"} 1.0' in telemetry.render().decode()
        finally:
            telemetry.shutdown()

    request = ExportMetricsServiceRequest.FromString(payloads.get(timeout=1))
    resource_metrics = request.resource_metrics[0]
    resource = {attribute.key: attribute.value.string_value for attribute in resource_metrics.resource.attributes}
    metrics = {metric.name: metric for scope in resource_metrics.scope_metrics for metric in scope.metrics}
    point = metrics["airmux_test_requests"].sum.data_points[0]

    assert resource["service.name"] == expected_name
    assert {attribute.key: attribute.value.string_value for attribute in point.attributes} == {"outcome": "success"}
    assert point.as_int == 1
