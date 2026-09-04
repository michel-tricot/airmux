from __future__ import annotations

import stat

import yaml
from helpers import run_in_db, setup_db
from pg import db_name_for, ensure_database
from typer.testing import CliRunner

from control_plane.config import validate_data_plane_token
from control_plane.main import app as cli_app
from control_plane.models import User, set_actor

runner = CliRunner()


def test_bootstrap_keygen_writes_one_private_pool_key(tmp_path):
    key_path = tmp_path / "dataplane.key"
    result = runner.invoke(cli_app, ["bootstrap-keygen", "--out", str(key_path)])
    assert result.exit_code == 0, result.output
    validate_data_plane_token(key_path.read_text(encoding="utf-8"))
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_bootstrap_keygen_refuses_to_clobber_an_existing_key(tmp_path):
    key_path = tmp_path / "dataplane.key"
    assert runner.invoke(cli_app, ["bootstrap-keygen", "--out", str(key_path)]).exit_code == 0
    before = key_path.read_text(encoding="utf-8")
    result = runner.invoke(cli_app, ["bootstrap-keygen", "--out", str(key_path)])
    assert result.exit_code == 1
    assert key_path.read_text(encoding="utf-8") == before


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


def _config(tmp_path):
    cfg = tmp_path / "airllm.yml"
    url = setup_db(tmp_path)
    cfg.write_text(yaml.safe_dump({"control_plane": {"database": {"url": url}}}), encoding="utf-8")
    return cfg


def test_owner_promotes_an_existing_account(tmp_path):
    cfg = _config(tmp_path)

    async def add_user():
        user = User(email="someone@example.com", name="Someone")
        await set_actor(user.id)
        await user.save()

    run_in_db(tmp_path, add_user)

    result = runner.invoke(cli_app, ["owner", "--email", "someone@example.com", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "someone@example.com" in result.output
    assert run_in_db(tmp_path, lambda: User.first(User.email == "someone@example.com")).instance_role == "owner"


def test_owner_refuses_an_account_that_has_not_signed_up(tmp_path):
    cfg = _config(tmp_path)
    result = runner.invoke(cli_app, ["owner", "--email", "new@example.com", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "sign up" in result.output
    assert run_in_db(tmp_path, lambda: User.first(User.email == "new@example.com")) is None


def test_owner_reports_an_invalid_email_without_opening_the_database(tmp_path):
    result = runner.invoke(cli_app, ["owner", "--email", "not-an-email", "--config", str(tmp_path / "missing.yml")])
    assert result.exit_code == 1
    assert "email must be a valid address" in result.output


def test_owner_is_idempotent(tmp_path):
    cfg = _config(tmp_path)

    async def add_user():
        user = User(email="twice@example.com", name="Twice")
        await set_actor(user.id)
        await user.save()

    run_in_db(tmp_path, add_user)
    assert runner.invoke(cli_app, ["owner", "--email", "twice@example.com", "--config", str(cfg)]).exit_code == 0
    again = runner.invoke(cli_app, ["owner", "--email", "twice@example.com", "--config", str(cfg)])
    assert again.exit_code == 0, again.output
    assert "already" in again.output


def test_owner_refuses_a_service_account(tmp_path):
    """Instance authority belongs to a human; a machine principal gets keys, not the bit."""
    cfg = _config(tmp_path)

    async def add_robot():
        robot = User.new_service_account("robot")
        await set_actor(robot.id)
        return await robot.save()

    email = run_in_db(tmp_path, add_robot).email

    result = runner.invoke(cli_app, ["owner", "--email", email, "--config", str(cfg)])
    assert result.exit_code == 1
    assert run_in_db(tmp_path, lambda: User.first(User.email == email)).instance_role is None
