from __future__ import annotations

import stat

from typer.testing import CliRunner

from contract import private_key_from_b64, public_key_to_b64
from control_plane.main import app as cli_app

runner = CliRunner()


def test_keygen_writes_a_valid_pair(tmp_path):
    key_path = tmp_path / "signing.key"
    result = runner.invoke(cli_app, ["keygen", "--out", str(key_path)])
    assert result.exit_code == 0, result.output
    private = private_key_from_b64(key_path.read_text(encoding="utf-8"))
    assert (tmp_path / "signing.pub").read_text(encoding="utf-8") == public_key_to_b64(private.public_key())
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_keygen_refuses_to_clobber_an_existing_key(tmp_path):
    key_path = tmp_path / "signing.key"
    assert runner.invoke(cli_app, ["keygen", "--out", str(key_path)]).exit_code == 0
    before = key_path.read_text(encoding="utf-8")
    result = runner.invoke(cli_app, ["keygen", "--out", str(key_path)])
    assert result.exit_code == 1
    assert key_path.read_text(encoding="utf-8") == before


def test_keygen_force_rotates_the_key(tmp_path):
    key_path = tmp_path / "signing.key"
    assert runner.invoke(cli_app, ["keygen", "--out", str(key_path)]).exit_code == 0
    before = key_path.read_text(encoding="utf-8")
    before_inode = key_path.stat().st_ino
    result = runner.invoke(cli_app, ["keygen", "--out", str(key_path), "--force"])
    assert result.exit_code == 0, result.output
    assert key_path.read_text(encoding="utf-8") != before
    assert key_path.stat().st_ino != before_inode


def test_owner_reports_an_invalid_email_without_opening_the_database(tmp_path):
    result = runner.invoke(cli_app, ["owner", "--email", "not-an-email", "--config", str(tmp_path / "missing.yml")])
    assert result.exit_code == 1
    assert "email must be a valid address" in result.output
