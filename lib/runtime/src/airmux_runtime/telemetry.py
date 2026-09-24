from __future__ import annotations

import os
from typing import TYPE_CHECKING

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.metrics import Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST

if TYPE_CHECKING:
    from collections.abc import Callable

    from opentelemetry.metrics import Meter


def _otlp_enabled() -> bool:
    exporters = {exporter.strip() for exporter in os.getenv("OTEL_METRICS_EXPORTER", "").split(",") if exporter.strip()}
    return "otlp" in exporters


class MetricsTelemetry:
    content_type = CONTENT_TYPE_LATEST

    def __init__(self, service_name: str) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        readers: list[MetricReader] = [
            PrometheusMetricReader(disable_target_info=True, scope_info_enabled=False, registry=self.registry),
        ]
        if _otlp_enabled():
            readers.append(PeriodicExportingMetricReader(OTLPMetricExporter()))
        self._provider = MeterProvider(
            metric_readers=readers,
            resource=Resource.create({SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME") or service_name}),
            shutdown_on_exit=False,
        )
        self.meter: Meter = self._provider.get_meter(service_name)

    def render(self) -> bytes:
        return generate_latest(self.registry)

    def observable_gauge(self, name: str, description: str, value: Callable[[], int | float]) -> None:
        self.meter.create_observable_gauge(name, callbacks=(lambda _options: (Observation(value()),),), description=description)

    def shutdown(self) -> None:
        self._provider.shutdown()
