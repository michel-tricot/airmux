from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient
from helpers import setup_control_plane
from pg import db_name_for, ensure_database

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


def test_healthz_is_unauthenticated_and_touches_the_database(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        res = c.get("/healthz")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}
