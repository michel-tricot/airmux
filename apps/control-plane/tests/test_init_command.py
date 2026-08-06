from __future__ import annotations

from dotenv import dotenv_values
from helpers import EMAIL, run_in_db, run_init

from contract import private_key_from_b64, verify_inference_token
from control_plane.models import Bundle, MgmtToken, Model, Org, OrgMembership, Provider, User
from control_plane.setup import org_name_from_email
from control_plane.tokens import verify_management_token

ALL_ENV_KEYS = (
    "GW_BUNDLE_SIGNING_KEY",
    "GW_BUNDLE_PUBLIC_KEY",
    "GW_TOKEN_SIGNING_KEY",
    "GW_TOKEN_PUBLIC_KEY",
    "GW_ADMIN_MGMT_TOKEN",
    "GW_ORG_MGMT_TOKEN",
    "GW_DATAPLANE_TOKEN",
    "AIRLLM_TOKEN",
)


def _public_key(tmp_path):
    signing_key = dotenv_values(tmp_path / ".env")["GW_TOKEN_SIGNING_KEY"]
    assert signing_key
    return private_key_from_b64(signing_key).public_key()


def test_init_yields_a_fully_ready_instance(tmp_path):
    result = run_init(tmp_path)
    assert result.exit_code == 0, result.output
    env = {key: value for key, value in dotenv_values(tmp_path / ".env").items() if value}
    for key in ALL_ENV_KEYS:
        assert env.get(key), key
    assert (tmp_path / "airllm.yml").exists()
    assert (tmp_path / "taxonomy.yml").exists()
    public = _public_key(tmp_path)
    admin = run_in_db(tmp_path, lambda: User.first(User.email == EMAIL))
    assert admin is not None
    assert admin.instance_admin
    mgmt = verify_management_token(env["GW_ADMIN_MGMT_TOKEN"], public)
    assert mgmt is not None
    assert mgmt.org_id is None
    assert mgmt.user_id == admin.id
    org_claims = verify_management_token(env["GW_ORG_MGMT_TOKEN"], public)
    assert org_claims is not None
    assert org_claims.org_id == "org-dev"
    assert org_claims.user_id == admin.id
    dp_claims = verify_management_token(env["GW_DATAPLANE_TOKEN"], public)
    assert dp_claims is not None
    sa = run_in_db(tmp_path, lambda: User.get(dp_claims.user_id))
    assert sa is not None
    assert sa.service_account
    assert run_in_db(tmp_path, lambda: OrgMembership.get((sa.id, "org-dev"))) is not None
    caller = verify_inference_token(env["AIRLLM_TOKEN"], public)
    assert caller is not None
    assert caller.org_id == "org-dev"
    org_row = run_in_db(tmp_path, lambda: Org.get("org-dev"))
    assert org_row is not None
    assert org_row.name == "Example"
    providers = run_in_db(tmp_path, Provider.find)
    models = run_in_db(tmp_path, Model.find)
    assert {p.id for p in providers} == {"openai", "anthropic"}
    assert len(models) == 2
    bundles = run_in_db(tmp_path, Bundle.find)
    assert [b.version for b in bundles] == [1]


def test_init_is_idempotent(tmp_path):
    assert run_init(tmp_path).exit_code == 0
    before = dotenv_values(tmp_path / ".env")
    result = run_init(tmp_path)
    assert result.exit_code == 0, result.output
    assert dotenv_values(tmp_path / ".env") == before
    assert len(run_in_db(tmp_path, MgmtToken.find)) == 3
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
    assert run_in_db(tmp_path, lambda: Org.get("org-acme")) is not None
    org_token = dotenv_values(tmp_path / ".env")["GW_ORG_MGMT_TOKEN"]
    assert org_token
    claims = verify_management_token(org_token, _public_key(tmp_path))
    assert claims is not None
    assert claims.org_id == "org-acme"


def test_init_never_prints_tokens(tmp_path):
    result = run_init(tmp_path)
    assert result.exit_code == 0, result.output
    assert "ab-mgmt-" not in result.output
    assert "ab-inf-" not in result.output


def test_init_fails_without_a_taxonomy_file(tmp_path):
    result = run_init(tmp_path, taxonomy=None)
    assert result.exit_code == 1
    assert "taxonomy" in result.output
    assert not (tmp_path / "taxonomy.yml").exists()
    assert not (tmp_path / "cp.db").exists()


def test_init_remints_tokens_orphaned_by_a_database_reset(tmp_path):
    assert run_init(tmp_path).exit_code == 0
    before = dotenv_values(tmp_path / ".env")
    (tmp_path / "cp.db").unlink()
    result = run_init(tmp_path)
    assert result.exit_code == 0, result.output
    env = {key: value for key, value in dotenv_values(tmp_path / ".env").items() if value}
    public = _public_key(tmp_path)
    for name in ("GW_ADMIN_MGMT_TOKEN", "GW_ORG_MGMT_TOKEN", "GW_DATAPLANE_TOKEN", "AIRLLM_TOKEN"):
        assert env[name] != before[name], name
    admin = run_in_db(tmp_path, lambda: User.first(User.email == EMAIL))
    assert admin is not None
    org_claims = verify_management_token(env["GW_ORG_MGMT_TOKEN"], public)
    assert org_claims is not None
    assert org_claims.user_id == admin.id
    dp_claims = verify_management_token(env["GW_DATAPLANE_TOKEN"], public)
    assert dp_claims is not None
    assert run_in_db(tmp_path, lambda: User.get(dp_claims.user_id)) is not None
    assert run_in_db(tmp_path, lambda: OrgMembership.get((dp_claims.user_id, "org-dev"))) is not None


def test_org_name_derives_from_the_email_domain():
    assert org_name_from_email("michel@example.com") == "Example"
    assert org_name_from_email("michel@acme-corp.io") == "Acme Corp"
    assert org_name_from_email("a@sub.acme.io") == "Sub Acme"
    assert org_name_from_email("root@localhost") == "My Organization"
    assert org_name_from_email("nodomain") == "My Organization"
