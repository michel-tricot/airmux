from __future__ import annotations

from prometheus_client.parser import text_string_to_metric_families

from airmux_runtime.telemetry import MetricsTelemetry, _otlp_enabled


def test_metrics_telemetry_renders_an_isolated_prometheus_registry() -> None:
    first = MetricsTelemetry("first-service")
    second = MetricsTelemetry("second-service")
    counter = first.meter.create_counter("airmux_test_requests")

    counter.add(1, {"outcome": "success"})

    first_metrics = {family.name: family for family in text_string_to_metric_families(first.render().decode())}
    second_metrics = {family.name: family for family in text_string_to_metric_families(second.render().decode())}
    assert first_metrics["airmux_test_requests"].samples[0].value == 1
    assert "airmux_test_requests" not in second_metrics


def test_otlp_export_uses_the_standard_metrics_exporter_selection(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_METRICS_EXPORTER", raising=False)
    assert not _otlp_enabled()

    monkeypatch.setenv("OTEL_METRICS_EXPORTER", "prometheus,otlp")
    assert _otlp_enabled()

    monkeypatch.setenv("OTEL_METRICS_EXPORTER", "none")
    assert not _otlp_enabled()
