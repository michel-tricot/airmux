from __future__ import annotations

import stat

from typer.testing import CliRunner

from control_plane.keys import validate_management_key_token
from control_plane.main import app as cli_app

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


def test_owner_reports_an_invalid_email_without_opening_the_database(tmp_path):
    result = runner.invoke(cli_app, ["owner", "--email", "not-an-email", "--config", str(tmp_path / "missing.yml")])
    assert result.exit_code == 1
    assert "email must be a valid address" in result.output
