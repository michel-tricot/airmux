from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from helpers import setup_control_plane
from pg import db_name_for, ensure_database

from contract import private_key_to_b64
from control_plane.app import create_app
from control_plane.config import BundlePolicy, DatabaseConfig, Settings


def test_serve_refuses_an_unmigrated_database(tmp_path):
    """Fail at startup with the fix named, never one 500 per request against a schemaless database."""
    url = ensure_database(db_name_for(tmp_path))
    settings = Settings(database=DatabaseConfig(url=url), bundle=BundlePolicy(signing_key=private_key_to_b64(Ed25519PrivateKey.generate())))
    with pytest.raises(RuntimeError, match="airllmcp migrate"), TestClient(create_app(settings)):
        pass


def test_healthz_is_unauthenticated_and_touches_the_database(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        res = c.get("/healthz")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}
