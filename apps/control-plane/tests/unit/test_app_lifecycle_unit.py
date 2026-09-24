from __future__ import annotations

import io
import json
import logging

import pytest
from prometheus_client.parser import text_string_to_metric_families

import control_plane.app as app_module
from airmux_runtime.observability import BatchedStreamHandler, JsonFormatter
from control_plane.app import create_app, lifespan
from control_plane.config import DatabaseConfig, Settings
from control_plane.db import make_engine
from control_plane.metrics import ControlPlaneMetrics


def test_management_routes_use_the_api_prefix():
    settings = Settings(
        database=DatabaseConfig(url="postgresql+asyncpg://unused:unused@127.0.0.1/unused"),
    )
    paths = set(create_app(settings).openapi()["paths"])
    assert "/api/v1/auth/me" in paths
    assert not any(path.startswith("/v1/") for path in paths)
    assert not {"/healthz", "/readyz", "/metrics"} & paths


def test_app_factories_have_isolated_metric_providers():
    settings = Settings(database=DatabaseConfig(url="postgresql+asyncpg://unused:unused@127.0.0.1/unused"))
    first = create_app(settings)
    second = create_app(settings)
    first.state.metrics.observe_throttle("allowed")
    assert first.state.metrics.render() != second.state.metrics.render()


def test_bundle_backlog_metrics_track_continuous_pending_work(monkeypatch):
    moments = iter((10.0, 16.0, 20.0))
    monkeypatch.setattr("control_plane.metrics.time.monotonic", lambda: next(moments))
    metrics = ControlPlaneMetrics()

    metrics.observe_bundle_backlog(2)
    metrics.observe_bundle_backlog(1)
    samples = {sample.name: sample.value for family in text_string_to_metric_families(metrics.render().decode()) for sample in family.samples}
    assert samples["airmux_control_plane_bundle_publication_pending"] == 1
    assert samples["airmux_control_plane_bundle_publication_oldest_age_seconds"] == 6

    metrics.observe_bundle_backlog(0)
    samples = {sample.name: sample.value for family in text_string_to_metric_families(metrics.render().decode()) for sample in family.samples}
    assert samples["airmux_control_plane_bundle_publication_pending"] == 0
    assert samples["airmux_control_plane_bundle_publication_oldest_age_seconds"] == 0


@pytest.mark.parametrize("failure", ["password_workers", "engine", "metrics"])
async def test_startup_failure_flushes_logs_even_when_resource_cleanup_fails(monkeypatch, failure):
    settings = Settings(database=DatabaseConfig(url="postgresql+asyncpg://unused:unused@127.0.0.1/unused"))
    app = create_app(settings)
    engine = make_engine(settings.database.url)
    stream = io.StringIO()
    handler = BatchedStreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    monkeypatch.setattr(app_module.logger, "handlers", [handler])
    monkeypatch.setattr(app_module.logger, "level", logging.INFO)
    monkeypatch.setattr(app_module, "make_engine", lambda _url: engine)

    async def refuse_schema(_engine):
        app_module.logger.info("startup_failed")
        message = "schema unavailable"
        raise ValueError(message)

    def fail_cleanup():
        message = f"{failure} cleanup failed"
        raise RuntimeError(message)

    async def fail_dispose():
        fail_cleanup()

    monkeypatch.setattr(app_module, "_require_migrated_schema", refuse_schema)
    workers_close = app.state.password_workers.close
    metrics_shutdown = app.state.metrics.shutdown
    engine_dispose = engine.dispose
    if failure == "engine":
        monkeypatch.setattr(type(engine), "dispose", lambda _engine: fail_dispose())
    elif failure == "password_workers":
        monkeypatch.setattr(app.state.password_workers, "close", fail_cleanup)
    else:
        monkeypatch.setattr(app.state.metrics, "shutdown", fail_cleanup)
    try:
        with pytest.raises(RuntimeError, match=f"{failure} cleanup failed"):
            async with lifespan(app):
                pytest.fail("startup should have failed")
        assert [json.loads(line)["message"] for line in stream.getvalue().splitlines()] == ["startup_failed"]
    finally:
        workers_close()
        await engine_dispose()
        metrics_shutdown()
        handler.close()
