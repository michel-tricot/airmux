from __future__ import annotations

import stat

import yaml
from pg import db_name_for, ensure_database
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
    result = runner.invoke(cli_app, ["keygen", "--out", str(key_path), "--force"])
    assert result.exit_code == 0, result.output
    assert key_path.read_text(encoding="utf-8") != before


def test_migrate_reports_what_it_did(tmp_path):
    """Silent success reads as failure: migrate names the database, the revisions applied, and the already-current case."""
    cfg = tmp_path / "airllm.yml"
    cfg.write_text(yaml.safe_dump({"control_plane": {"database": {"url": ensure_database(db_name_for(tmp_path))}}}), encoding="utf-8")
    first = runner.invoke(cli_app, ["migrate", "--config", str(cfg)])
    assert first.exit_code == 0, first.output
    assert "empty ->" in first.output
    assert db_name_for(tmp_path) in first.output
    again = runner.invoke(cli_app, ["migrate", "--config", str(cfg)])
    assert again.exit_code == 0, again.output
    assert "already at" in again.output
