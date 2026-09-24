from __future__ import annotations

import os

from typer.testing import CliRunner

from cli.control_plane import control_plane_app as cli_app

runner = CliRunner()


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
