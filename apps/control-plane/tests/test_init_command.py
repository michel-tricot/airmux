from __future__ import annotations

import yaml
from dotenv import dotenv_values
from helpers import EMAIL, cli_app, run_in_db, run_init
from pg import database_is_empty, db_name_for, drop_database, ensure_database
from typer.testing import CliRunner

from contract import INFERENCE_TOKEN_PREFIX, token_hash
from control_plane.keys import verify_management_key
from control_plane.models import Bundle, InferenceKey, ManagementKey, Model, Org, OrgMembership, Provider, User

ALL_ENV_KEYS = (
    "GW_BUNDLE_SIGNING_KEY",
    "GW_BUNDLE_PUBLIC_KEY",
    "GW_ADMIN_MGMT_TOKEN",
    "GW_ORG_MGMT_TOKEN",
    "GW_DATAPLANE_TOKEN",
    "AIRLLM_TOKEN",
)


def _verify(tmp_path, token):
    return run_in_db(tmp_path, lambda: verify_management_key(token))


def test_init_yields_a_fully_ready_instance(tmp_path):
    result = run_init(tmp_path)
    assert result.exit_code == 0, result.output
    env = {key: value for key, value in dotenv_values(tmp_path / ".env").items() if value}
    for key in ALL_ENV_KEYS:
        assert env.get(key), key
    assert (tmp_path / "airllm.yml").exists()
    assert (tmp_path / "taxonomy.yml").exists()
    admin = run_in_db(tmp_path, lambda: User.first(User.email == EMAIL))
    assert admin is not None
    assert admin.instance_admin
    mgmt = _verify(tmp_path, env["GW_ADMIN_MGMT_TOKEN"])
    assert mgmt is not None
    assert mgmt.org_id is None
    assert mgmt.user_id == admin.id
    org_row = run_in_db(tmp_path, lambda: Org.first(Org.name == "org-dev"))
    assert org_row is not None
    org_claims = _verify(tmp_path, env["GW_ORG_MGMT_TOKEN"])
    assert org_claims is not None
    assert org_claims.org_id == org_row.id
    assert org_claims.user_id == admin.id
    dp_claims = _verify(tmp_path, env["GW_DATAPLANE_TOKEN"])
    assert dp_claims is not None
    sa = run_in_db(tmp_path, lambda: User.find_by_id(dp_claims.user_id))
    assert sa is not None
    assert sa.service_account
    assert run_in_db(tmp_path, lambda: OrgMembership.get((sa.id, org_row.id))) is not None
    assert env["AIRLLM_TOKEN"].startswith(INFERENCE_TOKEN_PREFIX)
    caller = run_in_db(tmp_path, lambda: InferenceKey.first(InferenceKey.token_hash == token_hash(env["AIRLLM_TOKEN"])))
    assert caller is not None
    assert caller.org_id == org_row.id
    assert not caller.revoked
    assert caller.user_id == sa.id
    assert yaml.safe_load((tmp_path / "airllm.yml").read_text(encoding="utf-8"))["data_plane"]["bundle"]["org"] == str(org_row.id)
    providers = run_in_db(tmp_path, Provider.find)
    models = run_in_db(tmp_path, Model.find)
    assert {p.name for p in providers} == {"openai", "anthropic"}
    assert len(models) == 2
    bundles = run_in_db(tmp_path, Bundle.find)
    assert [b.version for b in bundles] == [1]


def test_init_is_idempotent(tmp_path):
    assert run_init(tmp_path).exit_code == 0
    before = dotenv_values(tmp_path / ".env")
    result = run_init(tmp_path)
    assert result.exit_code == 0, result.output
    assert dotenv_values(tmp_path / ".env") == before
    assert len(run_in_db(tmp_path, ManagementKey.find)) == 3
    assert [b.version for b in run_in_db(tmp_path, Bundle.find)] == [1]
    users = run_in_db(tmp_path, User.find)
    assert len(users) == 2


def test_init_prompts_for_email_when_not_given(tmp_path):
    result = run_init(tmp_path, stdin=f"{EMAIL}\n")
    assert result.exit_code == 0, result.output
    assert "Admin email" in result.output
    assert dotenv_values(tmp_path / ".env").get("GW_ADMIN_MGMT_TOKEN")


def test_init_skip_key_mints_no_caller_token(tmp_path):
    result = run_init(tmp_path, "--skip-key")
    assert result.exit_code == 0, result.output
    env = dotenv_values(tmp_path / ".env")
    assert env.get("GW_ORG_MGMT_TOKEN")
    assert env.get("AIRLLM_TOKEN") is None


def test_init_custom_org(tmp_path):
    result = run_init(tmp_path, "--org", "org-acme")
    assert result.exit_code == 0, result.output
    org_row = run_in_db(tmp_path, lambda: Org.first(Org.name == "org-acme"))
    assert org_row is not None
    org_token = dotenv_values(tmp_path / ".env")["GW_ORG_MGMT_TOKEN"]
    assert org_token
    claims = _verify(tmp_path, org_token)
    assert claims is not None
    assert claims.org_id == org_row.id


def test_init_never_prints_tokens(tmp_path):
    result = run_init(tmp_path)
    assert result.exit_code == 0, result.output
    assert "sk-mgmt-" not in result.output
    assert "sk-inf-" not in result.output


def test_migrate_reports_what_it_did(tmp_path):
    """Silent success reads as failure: migrate names the database, the revisions applied, and the already-current case."""
    cfg = tmp_path / "airllm.yml"
    cfg.write_text(yaml.safe_dump({"control_plane": {"database": {"url": ensure_database(db_name_for(tmp_path))}}}), encoding="utf-8")
    first = CliRunner().invoke(cli_app, ["migrate", "--config", str(cfg)])
    assert first.exit_code == 0, first.output
    assert "empty ->" in first.output
    assert db_name_for(tmp_path) in first.output
    again = CliRunner().invoke(cli_app, ["migrate", "--config", str(cfg)])
    assert again.exit_code == 0, again.output
    assert "already at" in again.output


def test_init_fails_without_a_taxonomy_file(tmp_path):
    result = run_init(tmp_path, taxonomy=None)
    assert result.exit_code == 1
    assert "taxonomy" in result.output
    assert not (tmp_path / "taxonomy.yml").exists()
    assert database_is_empty(tmp_path)


def test_init_remints_tokens_orphaned_by_a_database_reset(tmp_path):
    assert run_init(tmp_path).exit_code == 0
    before = dotenv_values(tmp_path / ".env")
    drop_database(db_name_for(tmp_path))
    ensure_database(db_name_for(tmp_path))
    result = run_init(tmp_path)
    assert result.exit_code == 0, result.output
    env = {key: value for key, value in dotenv_values(tmp_path / ".env").items() if value}
    for name in ("GW_ADMIN_MGMT_TOKEN", "GW_ORG_MGMT_TOKEN", "GW_DATAPLANE_TOKEN", "AIRLLM_TOKEN"):
        assert env[name] != before[name], name
    admin = run_in_db(tmp_path, lambda: User.first(User.email == EMAIL))
    assert admin is not None
    org_claims = _verify(tmp_path, env["GW_ORG_MGMT_TOKEN"])
    assert org_claims is not None
    assert org_claims.user_id == admin.id
    dp_claims = _verify(tmp_path, env["GW_DATAPLANE_TOKEN"])
    assert dp_claims is not None
    assert run_in_db(tmp_path, lambda: User.find_by_id(dp_claims.user_id)) is not None
    org_row = run_in_db(tmp_path, lambda: Org.first(Org.name == "org-dev"))
    assert org_row is not None
    assert run_in_db(tmp_path, lambda: OrgMembership.get((dp_claims.user_id, org_row.id))) is not None
