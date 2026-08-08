from __future__ import annotations

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from helpers import EMAIL, run_in_db, setup_control_plane, write_config
from typer.testing import CliRunner

from control_plane.keys import verify_management_key
from control_plane.main import app
from control_plane.models import AuditLog, ManagementKey, User, set_actor

runner = CliRunner()


def _create(tmp_path, cfg: str, *extra: str):
    return runner.invoke(app, ["admin", "create", EMAIL, "--config", cfg, "--env-file", str(tmp_path / ".env"), *extra])


async def _seed_user(instance_admin: bool, service_account: bool) -> User:
    user = User(email=EMAIL, name="seeded", instance_admin=instance_admin, service_account=service_account)
    await set_actor(user.id)
    return await user.save()


def test_create_mints_a_user_bound_instance_token(tmp_path):
    cp = setup_control_plane(tmp_path)
    result = _create(tmp_path, write_config(tmp_path, cp))
    assert result.exit_code == 0, result.output
    token = dotenv_values(tmp_path / ".env")["GW_ADMIN_MGMT_TOKEN"]
    assert token is not None
    claims = run_in_db(tmp_path, lambda: verify_management_key(token))
    assert claims is not None
    assert claims.org_id is None
    user = run_in_db(tmp_path, lambda: User.first(User.email == EMAIL))
    assert user is not None
    assert user.instance_admin
    assert not user.service_account
    assert claims.user_id == user.id
    row = run_in_db(tmp_path, lambda: ManagementKey.find_by_id(claims.token_id))
    assert row is not None
    assert row.user_id == user.id
    assert not row.revoked
    with TestClient(cp.app) as c:
        assert c.get("/v1/orgs", headers={"authorization": f"Bearer {token}"}).status_code == 200


def test_create_audits_as_the_new_admin(tmp_path):
    cp = setup_control_plane(tmp_path)
    assert _create(tmp_path, write_config(tmp_path, cp)).exit_code == 0
    user = run_in_db(tmp_path, lambda: User.first(User.email == EMAIL))
    assert user is not None
    entries = run_in_db(tmp_path, lambda: AuditLog.find(AuditLog.table_name == "user"))
    assert [(e.action, e.user_id) for e in entries] == [("create", str(user.id))]


def test_existing_admin_gets_a_fresh_token(tmp_path):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    assert _create(tmp_path, cfg).exit_code == 0
    first = dotenv_values(tmp_path / ".env")["GW_ADMIN_MGMT_TOKEN"]
    result = _create(tmp_path, cfg)
    assert result.exit_code == 0, result.output
    second = dotenv_values(tmp_path / ".env")["GW_ADMIN_MGMT_TOKEN"]
    assert second is not None
    assert second != first
    users = run_in_db(tmp_path, User.find)
    assert [u.email for u in users] == [EMAIL]
    tokens = run_in_db(tmp_path, ManagementKey.find)
    assert len(tokens) == 2
    assert {t.user_id for t in tokens} == {users[0].id}


def test_if_missing_skips_an_existing_admin(tmp_path):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    assert _create(tmp_path, cfg).exit_code == 0
    before = dotenv_values(tmp_path / ".env")
    result = _create(tmp_path, cfg, "--if-missing")
    assert result.exit_code == 0, result.output
    assert dotenv_values(tmp_path / ".env") == before
    assert len(run_in_db(tmp_path, ManagementKey.find)) == 1


@pytest.mark.parametrize(("instance_admin", "service_account"), [(False, False), (True, True)])
def test_refuses_emails_that_are_not_human_admins(tmp_path, instance_admin, service_account):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    run_in_db(tmp_path, lambda: _seed_user(instance_admin, service_account))
    result = _create(tmp_path, cfg)
    assert result.exit_code == 1
    assert run_in_db(tmp_path, ManagementKey.find) == []
    assert not (tmp_path / ".env").exists()


@pytest.mark.parametrize(("instance_admin", "service_account"), [(False, False), (True, True)])
def test_if_missing_still_refuses_non_admin_emails(tmp_path, instance_admin, service_account):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    run_in_db(tmp_path, lambda: _seed_user(instance_admin, service_account))
    assert _create(tmp_path, cfg, "--if-missing").exit_code == 1
