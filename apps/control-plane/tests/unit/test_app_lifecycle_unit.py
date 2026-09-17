from __future__ import annotations

from prometheus_client import generate_latest
from prometheus_client.parser import text_string_to_metric_families

from control_plane.app import create_app
from control_plane.config import DatabaseConfig, Settings
from control_plane.metrics import ControlPlaneMetrics


def test_management_routes_use_the_api_prefix():
    settings = Settings(
        database=DatabaseConfig(url="postgresql+asyncpg://unused:unused@127.0.0.1/unused"),
    )
    paths = set(create_app(settings).openapi()["paths"])
    assert "/api/v1/auth/me" in paths
    assert not any(path.startswith("/v1/") for path in paths)
    assert not {"/healthz", "/readyz", "/metrics"} & paths


def test_app_factories_have_isolated_metric_registries():
    settings = Settings(database=DatabaseConfig(url="postgresql+asyncpg://unused:unused@127.0.0.1/unused"))
    first = create_app(settings)
    second = create_app(settings)
    assert first.state.metrics.registry is not second.state.metrics.registry


def test_bundle_backlog_metrics_track_continuous_pending_work(monkeypatch):
    moments = iter((10.0, 16.0, 20.0))
    monkeypatch.setattr("control_plane.metrics.time.monotonic", lambda: next(moments))
    metrics = ControlPlaneMetrics()

    metrics.observe_bundle_backlog(2)
    metrics.observe_bundle_backlog(1)
    samples = {
        sample.name: sample.value
        for family in text_string_to_metric_families(generate_latest(metrics.registry).decode())
        for sample in family.samples
    }
    assert samples["airmux_control_plane_bundle_publication_pending"] == 1
    assert samples["airmux_control_plane_bundle_publication_oldest_age_seconds"] == 6

    metrics.observe_bundle_backlog(0)
    samples = {
        sample.name: sample.value
        for family in text_string_to_metric_families(generate_latest(metrics.registry).decode())
        for sample in family.samples
    }
    assert samples["airmux_control_plane_bundle_publication_pending"] == 0
    assert samples["airmux_control_plane_bundle_publication_oldest_age_seconds"] == 0
