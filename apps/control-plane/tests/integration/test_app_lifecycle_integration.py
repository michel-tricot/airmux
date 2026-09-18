from __future__ import annotations

import contextlib
from uuid import UUID

import pytest
import yaml
from fastapi.testclient import TestClient
from helpers import setup_control_plane
from pg import db_name_for, ensure_database
from sqlalchemy.exc import SQLAlchemyError

from control_plane.app import create_app
from control_plane.config import DatabaseConfig, Settings
from control_plane.migrate import current_revision, head_revision
from control_plane.operations import serve


def test_serve_refuses_an_unmigrated_database(tmp_path):
    """Fail at startup with the fix named, never one 500 per request against a schemaless database."""
    url = ensure_database(db_name_for(tmp_path))
    settings = Settings(database=DatabaseConfig(url=url))
    with pytest.raises(RuntimeError, match="airmux control-plane migrate"), TestClient(create_app(settings)):
        pass


@pytest.mark.parametrize(("dev", "expected_revision"), [(False, None), (True, head_revision())])
def test_only_dev_serve_migrates_the_database(tmp_path, monkeypatch, dev, expected_revision):
    url = ensure_database(db_name_for(tmp_path))
    config = tmp_path / "airmux.yml"
    config.write_text(yaml.safe_dump({"control_plane": {"database": {"url": url}}}), encoding="utf-8")
    monkeypatch.setattr("control_plane.operations.uvicorn.run", lambda *args, **kwargs: None)

    serve(config, host="127.0.0.1", port=8000, dev=dev)

    assert current_revision(url) == expected_revision


def test_liveness_readiness_metrics_and_request_correlation(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        health = c.get("/healthz", headers={"x-request-id": "caller-controlled"})
        readiness = c.get("/readyz")
        metrics = c.get("/metrics").text
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        assert readiness.status_code == 200
        assert readiness.json() == {"status": "ready"}
        assert health.headers["x-request-id"] != "caller-controlled"
        assert UUID(health.headers["x-request-id"]).version == 7
        assert "airmux_control_plane_http_requests_total" in metrics
        assert 'route="/healthz"' in metrics
        assert not any(forbidden in metrics for forbidden in ("org_id=", "workspace_id=", "user_id=", "request_id="))
        assert c.post("/api/v1/events", json=[]).status_code == 401
        rejected_metrics = c.get("/metrics").text
        assert 'airmux_control_plane_event_ingest_total{outcome="rejected"} 1.0' in rejected_metrics

        @contextlib.asynccontextmanager
        async def unavailable_database():
            message = "database unavailable"
            raise SQLAlchemyError(message)
            yield

        cp.app.state.session_factory = unavailable_database
        assert c.get("/healthz").status_code == 200
        unavailable = c.get("/readyz")
        assert unavailable.status_code == 503
        assert unavailable.json() == {"status": "unavailable"}
