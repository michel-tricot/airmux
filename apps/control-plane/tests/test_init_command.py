from __future__ import annotations

from dotenv import dotenv_values
from helpers import EMAIL, run_in_db, run_init

from contract import INFERENCE_TOKEN_PREFIX, token_hash
from control_plane.models import ApiKey, Bundle, MgmtToken, Model, Org, OrgMembership, Provider, User
from control_plane.setup import org_name_from_email
from control_plane.tokens import verify_management_token

ALL_ENV_KEYS = (
    "GW_BUNDLE_SIGNING_KEY",
    "GW_BUNDLE_PUBLIC_KEY",
    "GW_ADMIN_MGMT_TOKEN",
    "GW_ORG_MGMT_TOKEN",
    "GW_DATAPLANE_TOKEN",
    "AIRLLM_TOKEN",
)


def _verify(tmp_path, token):
    return run_in_db(tmp_path, lambda: verify_management_token(token))


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
    org_claims = _verify(tmp_path, env["GW_ORG_MGMT_TOKEN"])
    assert org_claims is not None
    assert org_claims.org_id == "org-dev"
    assert org_claims.user_id == admin.id
    dp_claims = _verify(tmp_path, env["GW_DATAPLANE_TOKEN"])
    assert dp_claims is not None
    sa = run_in_db(tmp_path, lambda: User.get(dp_claims.user_id))
    assert sa is not None
    assert sa.service_account
    assert run_in_db(tmp_path, lambda: OrgMembership.get((sa.id, "org-dev"))) is not None
    assert env["AIRLLM_TOKEN"].startswith(INFERENCE_TOKEN_PREFIX)
    caller = run_in_db(tmp_path, lambda: ApiKey.first(ApiKey.token_hash == token_hash(env["AIRLLM_TOKEN"])))
    assert caller is not None
    assert caller.org_id == "org-dev"
    assert not caller.disabled
    assert caller.user_id == sa.id
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
    claims = _verify(tmp_path, org_token)
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
    for name in ("GW_ADMIN_MGMT_TOKEN", "GW_ORG_MGMT_TOKEN", "GW_DATAPLANE_TOKEN", "AIRLLM_TOKEN"):
        assert env[name] != before[name], name
    admin = run_in_db(tmp_path, lambda: User.first(User.email == EMAIL))
    assert admin is not None
    org_claims = _verify(tmp_path, env["GW_ORG_MGMT_TOKEN"])
    assert org_claims is not None
    assert org_claims.user_id == admin.id
    dp_claims = _verify(tmp_path, env["GW_DATAPLANE_TOKEN"])
    assert dp_claims is not None
    assert run_in_db(tmp_path, lambda: User.get(dp_claims.user_id)) is not None
    assert run_in_db(tmp_path, lambda: OrgMembership.get((dp_claims.user_id, "org-dev"))) is not None


def test_org_name_derives_from_the_email_domain():
    assert org_name_from_email("michel@example.com") == "Example"
    assert org_name_from_email("michel@acme-corp.io") == "Acme Corp"
    assert org_name_from_email("a@sub.acme.io") == "Sub Acme"
    assert org_name_from_email("root@localhost") == "My Organization"
    assert org_name_from_email("nodomain") == "My Organization"
