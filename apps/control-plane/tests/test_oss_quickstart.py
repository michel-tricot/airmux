from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from helpers import run_in_db, setup_control_plane

from contract import uuid7
from control_plane.models import DataPlaneInstance
from control_plane.routes import instance

TOKEN = "sk-mgmt-quickstart-token"


@pytest.fixture
def key_path(tmp_path, monkeypatch):
    path = tmp_path / "state" / "dataplane.key"
    monkeypatch.setattr(instance, "DATA_PLANE_KEY_PATH", path)
    return path


def _register_instance(tmp_path) -> None:
    async def insert() -> None:
        now = datetime.now(tz=UTC)
        await DataPlaneInstance(instance_id=uuid7(), version="0.1.0", first_seen=now, last_seen=now).save()

    run_in_db(tmp_path, insert)


def test_oss_quickstart_writes_the_token_on_a_virgin_instance(tmp_path, key_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        resp = c.post("/v1/instance/oss-quickstart", json={"token": TOKEN})
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["path"] == str(key_path)
        assert key_path.read_text(encoding="utf-8") == TOKEN


def test_oss_quickstart_is_public(tmp_path, key_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        assert c.post("/v1/instance/oss-quickstart", json={"token": TOKEN}).status_code == 200


def test_oss_quickstart_closes_once_a_data_plane_has_registered(tmp_path, key_path):
    cp = setup_control_plane(tmp_path)
    _register_instance(tmp_path)
    with TestClient(cp.app) as c:
        resp = c.post("/v1/instance/oss-quickstart", json={"token": TOKEN})
        assert resp.status_code == 409
        assert not key_path.exists()


def test_oss_quickstart_rejects_a_token_without_the_management_prefix(tmp_path, key_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        resp = c.post("/v1/instance/oss-quickstart", json={"token": "not-a-mgmt-token"})
        assert resp.status_code == 422
        assert not key_path.exists()
