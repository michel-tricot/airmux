from __future__ import annotations

import os
import stat

from typer.testing import CliRunner

from cli.control_plane import control_plane_app as cli_app
from control_plane.keys import validate_management_key_token

runner = CliRunner()


def test_bootstrap_keygen_writes_one_private_pool_key(tmp_path):
    key_path = tmp_path / "dataplane.key"
    result = runner.invoke(cli_app, ["bootstrap-keygen", "--out", str(key_path)])
    assert result.exit_code == 0, result.output
    validate_management_key_token(key_path.read_text(encoding="utf-8"))
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_bootstrap_keygen_refuses_to_clobber_an_existing_key(tmp_path):
    key_path = tmp_path / "dataplane.key"
    assert runner.invoke(cli_app, ["bootstrap-keygen", "--out", str(key_path)]).exit_code == 0
    before = key_path.read_text(encoding="utf-8")
    result = runner.invoke(cli_app, ["bootstrap-keygen", "--out", str(key_path)])
    assert result.exit_code == 1
    assert key_path.read_text(encoding="utf-8") == before


def test_migrate_restores_the_selected_configuration_after_failure(tmp_path, monkeypatch):
    selected = tmp_path / "selected.yml"
    config = tmp_path / "migration.yml"
    config.write_text("control_plane:\n  database:\n    url: ${env:MISSING_DATABASE_URL}\n", encoding="utf-8")
    monkeypatch.setenv("AIRMUX_CONFIG", str(selected))
    monkeypatch.delenv("MISSING_DATABASE_URL", raising=False)
    result = runner.invoke(cli_app, ["migrate", "--config", str(config)])
    assert result.exit_code == 1
    assert os.environ["AIRMUX_CONFIG"] == str(selected)


def test_owner_reports_an_invalid_email_without_opening_the_database(tmp_path):
    config = tmp_path / "airmux.yml"
    config.write_text("control_plane: {}\n")
    result = runner.invoke(cli_app, ["owner", "--email", "not-an-email", "--config", str(config)])
    assert result.exit_code == 1
    assert "email must be a valid address" in result.output
