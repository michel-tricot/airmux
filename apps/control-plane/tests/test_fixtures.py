"""Development fixtures seed a fresh instance only, and refuse a database that is already somebody's.

There is no merge and no partial reset, so this refusal is the whole contract worth holding: to
reseed, drop the database and recreate it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from helpers import run_in_db, setup_control_plane, write_config
from typer.testing import CliRunner

from contract import MemoryStoreConfig
from control_plane.fixtures import NotAnEmptyDatabaseError, apply_fixtures
from control_plane.main import app as cli_app
from control_plane.models import Org

runner = CliRunner()

CSRF = {"X-Requested-With": "fetch"}
NOW = datetime(2026, 8, 9, tzinfo=UTC)


def test_apply_refuses_a_database_that_already_holds_accounts(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        c.post("/v1/auth/signup", json={"email": "real@example.com", "password": "hunter2hunter2", "name": "Real"}, headers=CSRF)

    with pytest.raises(NotAnEmptyDatabaseError):
        run_in_db(tmp_path, lambda: apply_fixtures(NOW, MemoryStoreConfig().build()))

    assert run_in_db(tmp_path, Org.find) == []


def test_cli_refuses_a_database_that_is_not_empty(tmp_path):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    with TestClient(cp.app) as c:
        c.post("/v1/auth/signup", json={"email": "real@example.com", "password": "hunter2hunter2", "name": "Real"}, headers=CSRF)

    refused = runner.invoke(cli_app, ["fixtures", "--config", cfg])

    assert refused.exit_code == 1
    assert "not an empty database" in refused.output
    assert run_in_db(tmp_path, Org.find) == []
