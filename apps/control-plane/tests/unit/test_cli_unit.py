from __future__ import annotations

import os
import stat

from typer.testing import CliRunner

from cli.control_plane import control_plane_app as cli_app
from control_plane.keys import validate_management_key_token

runner = CliRunner()


def test_bootstrap_keygen_ensures_the_configured_private_pool_key(tmp_path):
    config = tmp_path / "airmux.yml"
    config.write_text("control_plane:\n  bootstrap:\n    token: ${file:state/runtime/dataplane.key}\n", encoding="utf-8")
    key_path = tmp_path / "state/runtime/dataplane.key"

    result = runner.invoke(cli_app, ["bootstrap-keygen", "--config", str(config)])
    assert result.exit_code == 0, result.output
    validate_management_key_token(key_path.read_text(encoding="utf-8"))
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    before = key_path.read_text(encoding="utf-8")

    result = runner.invoke(cli_app, ["bootstrap-keygen", "--config", str(config)])
    assert result.exit_code == 0, result.output
    assert key_path.read_text(encoding="utf-8") == before


def test_bootstrap_keygen_requires_a_file_reference(tmp_path):
    config = tmp_path / "airmux.yml"
    config.write_text("control_plane:\n  bootstrap:\n    token: ${env:DATA_PLANE_TOKEN}\n", encoding="utf-8")

    result = runner.invoke(cli_app, ["bootstrap-keygen", "--config", str(config)])

    assert result.exit_code == 1
    assert "control_plane.bootstrap.token must be a file reference" in result.output


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
