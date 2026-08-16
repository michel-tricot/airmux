from __future__ import annotations

import stat
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from helpers import run_in_db, setup_control_plane

from contract import INFERENCE_TOKEN_PREFIX, uuid7
from control_plane.keys import INSTANCE_KEY_PREFIX, MANAGEMENT_KEY_PREFIX
from control_plane.models import DataPlaneInstance
from control_plane.routes import oss

TOKEN = INSTANCE_KEY_PREFIX + "quickstart-token"


@pytest.fixture
def key_path(tmp_path, monkeypatch):
    """The token lands at the one relative path the shipped config names, resolved from the working directory.

    In the container that working directory is the shared /state volume, so the same
    .airllm/dataplane.key reaches the co-mounted data plane there and in a checkout.
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path / oss.DATA_PLANE_KEY_DIR / oss.DATA_PLANE_KEY_FILE


def _register_instance(tmp_path) -> None:
    async def insert() -> None:
        now = datetime.now(tz=UTC)
        await DataPlaneInstance(instance_id=uuid7(), version="0.1.0", first_seen=now, last_seen=now).save()

    run_in_db(tmp_path, insert)


def test_oss_quickstart_writes_the_token_on_a_virgin_instance(tmp_path, key_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        resp = c.post("/v1/instance/oss/quickstart", json={"token": TOKEN})
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["path"] == str(key_path)
        assert key_path.read_text(encoding="utf-8") == TOKEN
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_oss_quickstart_is_public(tmp_path, key_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        assert c.post("/v1/instance/oss/quickstart", json={"token": TOKEN}).status_code == 200


def test_oss_quickstart_closes_once_a_data_plane_has_registered(tmp_path, key_path):
    cp = setup_control_plane(tmp_path)
    _register_instance(tmp_path)
    with TestClient(cp.app) as c:
        resp = c.post("/v1/instance/oss/quickstart", json={"token": TOKEN})
        assert resp.status_code == 409
        assert not key_path.exists()


def test_oss_quickstart_rejects_a_token_that_could_never_drive_a_data_plane(tmp_path, key_path):
    """Either control-plane key type is accepted; an inference key or a paste accident is not."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        for token in ("not-a-key", INFERENCE_TOKEN_PREFIX + "caller-key", ""):
            resp = c.post("/v1/instance/oss/quickstart", json={"token": token})
            assert resp.status_code == 422, token
            assert not key_path.exists()


def test_oss_quickstart_accepts_a_management_key_too(tmp_path, key_path):
    """A single-org deployment hands its data plane an org key; quickstart writes it unchanged."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        management_token = MANAGEMENT_KEY_PREFIX + "org-scoped-token"
        assert c.post("/v1/instance/oss/quickstart", json={"token": management_token}).status_code == 200
        assert key_path.read_text(encoding="utf-8") == management_token


def test_oss_quickstart_creates_the_cache_directory(tmp_path, key_path):
    """A deployment that brought its own signing key never ran keygen, so nothing made .airllm first."""
    cp = setup_control_plane(tmp_path)
    assert not key_path.parent.exists()
    with TestClient(cp.app) as c:
        assert c.post("/v1/instance/oss/quickstart", json={"token": TOKEN}).status_code == 200
        assert key_path.read_text(encoding="utf-8") == TOKEN
