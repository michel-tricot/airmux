from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from helpers import run_in_db, setup_control_plane, write_config
from typer.testing import CliRunner

from contract import EnvStoreConfig, MemoryStoreConfig
from control_plane.authz import InstanceRole
from control_plane.fixtures import (
    ACME_MEMBER_INVITE_TOKEN,
    ACME_PRODUCTION_INVITE_TOKEN,
    FIXTURE_PROVIDER_KEY,
    MODELS,
    ExistingHumanAccountsError,
    MissingModelsError,
    MissingProvidersError,
    apply_fixtures,
)
from control_plane.main import app as cli_app
from control_plane.models import DataPlaneInstance, InferenceKey, Model, Org, OrgInvitation, Policy, Provider, ProviderCredential, User, set_actor

runner = CliRunner()


CSRF = {"X-Requested-With": "fetch"}


NOW = datetime(2026, 8, 9, tzinfo=UTC)


def seed_catalog(tmp_path, *, include_models=True):
    """The providers the fixtures route traffic to, as `airllmcp taxonomy` would leave them."""

    async def apply():
        await set_actor("root")
        providers = {}
        for name in ("openai", "anthropic"):
            providers[name] = await Provider(name=name, kind="openai_compatible", base_url=f"https://{name}.test/v1").save()
        if include_models:
            for name, provider_name in MODELS:
                await Model(
                    name=name,
                    provider_id=providers[provider_name].id,
                    upstream_model=name,
                    input_price_per_mtok=1,
                    output_price_per_mtok=2,
                    cache_read_price_per_mtok=0,
                    cache_write_price_per_mtok=0,
                    context_window=128000,
                    input_modalities=["text"],
                    output_modalities=["text"],
                ).save()

    run_in_db(tmp_path, apply)


def test_apply_refuses_a_database_that_already_holds_accounts(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        c.post("/api/v1/auth/signup", json={"email": "real@example.com", "password": "hunter2hunter2", "name": "Real"}, headers=CSRF)

    with pytest.raises(ExistingHumanAccountsError):
        run_in_db(tmp_path, lambda: apply_fixtures(NOW, MemoryStoreConfig().build()))

    assert run_in_db(tmp_path, Org.find) == []


def test_apply_allows_the_deployment_service_account(tmp_path):
    setup_control_plane(tmp_path)
    seed_catalog(tmp_path)

    async def bootstrap():
        await set_actor("root")
        await User.new_service_account("deployment data plane", instance_role=InstanceRole.data_plane).save()

    run_in_db(tmp_path, bootstrap)
    run_in_db(tmp_path, lambda: apply_fixtures(NOW, MemoryStoreConfig().build()))

    users = run_in_db(tmp_path, User.find)
    assert {user.service_account for user in users} == {True, False}
    assert {user.email for user in users if not user.service_account} == {"m@airbyte.com", "b@airbyte.com"}


def test_cli_refuses_a_database_that_already_has_a_human_account(tmp_path):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    with TestClient(cp.app) as c:
        c.post("/api/v1/auth/signup", json={"email": "real@example.com", "password": "hunter2hunter2", "name": "Real"}, headers=CSRF)

    refused = runner.invoke(cli_app, ["fixtures", "--config", cfg])

    assert refused.exit_code == 1
    assert "already has human accounts" in refused.output
    assert run_in_db(tmp_path, Org.find) == []


def test_seeding_refuses_a_catalog_without_the_providers_it_routes_to(tmp_path):
    """Fixtures populate a tenant, not the catalog: taxonomy owns which providers exist, and a
    fixture instance that invented its own would drift from the one an operator applies.

    Refusing beats seeding around the gap, because usage rows and credentials that name a provider
    nothing routes to are a fixture instance that looks populated and serves nothing.
    """
    setup_control_plane(tmp_path)
    with pytest.raises(MissingProvidersError, match="openai"):
        run_in_db(tmp_path, lambda: apply_fixtures(NOW, MemoryStoreConfig().build()))

    assert run_in_db(tmp_path, Org.find) == []


def test_the_cli_names_the_command_that_fills_the_catalog(tmp_path):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    refused = runner.invoke(cli_app, ["fixtures", "--config", cfg])

    assert refused.exit_code == 1
    assert "airllmcp taxonomy" in refused.output


def test_seeding_refuses_a_catalog_without_the_models_its_policies_use(tmp_path):
    setup_control_plane(tmp_path)
    seed_catalog(tmp_path, include_models=False)

    with pytest.raises(MissingModelsError, match="claude-opus-4-5"):
        run_in_db(tmp_path, lambda: apply_fixtures(NOW, MemoryStoreConfig().build()))

    assert run_in_db(tmp_path, Org.find) == []


def test_the_keys_are_seeded_whatever_the_store_can_hold(tmp_path, monkeypatch):
    """The env store is the default, so `airllmcp fixtures` on an unconfigured instance hits it.

    The rows are the fixture; the value beside them is the store's business. On the env store there
    is nothing to write because the ref already resolves to a variable the operator owns, so a
    developer with their own key set gets a pool that genuinely works.
    """
    setup_control_plane(tmp_path)
    seed_catalog(tmp_path)
    seeded = run_in_db(tmp_path, lambda: apply_fixtures(NOW, EnvStoreConfig().build()))
    credentials = run_in_db(tmp_path, ProviderCredential.find)

    assert credentials != []
    assert seeded.unresolved_providers == ["anthropic", "openai"]

    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-operators-own")
    openai_key = next(c for c in credentials if c.provider_name == "openai")
    assert asyncio.run(EnvStoreConfig().build().get(openai_key.secret_ref())).reveal() == "sk-the-operators-own"


def test_a_writable_store_gets_placeholder_values(tmp_path):
    """A placeholder no provider accepts, so a fixture instance cannot bill anyone by accident."""
    store = MemoryStoreConfig().build()
    setup_control_plane(tmp_path)
    seed_catalog(tmp_path)
    seeded = run_in_db(tmp_path, lambda: apply_fixtures(NOW, store))
    credentials = run_in_db(tmp_path, ProviderCredential.find)

    assert seeded.unresolved_providers == []
    for credential in credentials:
        assert asyncio.run(store.get(credential.secret_ref())).reveal() == FIXTURE_PROVIDER_KEY


def test_invitation_fixtures_include_org_and_workspace_share_links(tmp_path):
    setup_control_plane(tmp_path)
    seed_catalog(tmp_path)

    seeded = run_in_db(tmp_path, lambda: apply_fixtures(NOW, MemoryStoreConfig().build()))
    invitations = run_in_db(tmp_path, OrgInvitation.find)
    member_invitation = run_in_db(tmp_path, lambda: OrgInvitation.for_token(ACME_MEMBER_INVITE_TOKEN))
    production_invitation = run_in_db(tmp_path, lambda: OrgInvitation.for_token(ACME_PRODUCTION_INVITE_TOKEN))

    assert seeded.invitation_tokens == [
        ("new.member@example.com", ACME_MEMBER_INVITE_TOKEN),
        ("production.viewer@example.com", ACME_PRODUCTION_INVITE_TOKEN),
    ]
    assert len(invitations) == 3
    assert member_invitation is not None
    assert member_invitation.workspace_id is None
    assert member_invitation.status(NOW) == "pending"
    assert production_invitation is not None
    assert production_invitation.workspace_id is not None
    assert production_invitation.workspace_role == "viewer"
    assert production_invitation.status(NOW) == "pending"
    assert next(invitation for invitation in invitations if invitation.email == "expired.invite@example.com").status(NOW) == "expired"


def test_policy_fixtures_cover_actions_targets_request_matches_and_states(tmp_path):
    setup_control_plane(tmp_path)
    seed_catalog(tmp_path)

    run_in_db(tmp_path, lambda: apply_fixtures(NOW, MemoryStoreConfig().build()))
    policies = run_in_db(tmp_path, Policy.find)
    inference_keys = run_in_db(tmp_path, InferenceKey.find)

    assert {rule.action.kind for policy in policies for rule in policy.definition.rules} == {
        "models",
        "providers",
        "deny",
        "strict_parameters",
        "price_limit",
        "request_limits",
        "credential_access",
        "fallback",
        "budget",
    }
    assert {policy.definition.target.kind for policy in policies} == {"all_keys", "selected_keys"}
    assert {policy.enabled for policy in policies} == {True, False}
    streaming_match = next(policy for policy in policies if policy.name == "Streaming uses team credentials").definition.rules[0].match
    assert streaming_match.kind == "request"
    assert streaming_match.stream is True
    ci_key = next(key for key in inference_keys if key.label == "ci")
    ci_policy = next(policy for policy in policies if policy.name == "CI provider allowlist")
    assert ci_policy.definition.target.kind == "selected_keys"
    assert ci_policy.definition.target.key_ids == (str(ci_key.id),)


def test_data_plane_fixtures_cover_global_and_dedicated_lifecycle_states(tmp_path):
    setup_control_plane(tmp_path)
    seed_catalog(tmp_path)

    run_in_db(tmp_path, lambda: apply_fixtures(NOW, MemoryStoreConfig().build()))
    instances = run_in_db(tmp_path, DataPlaneInstance.find)

    assert {instance.status(NOW) for instance in instances} == {"online", "offline"}
    assert {instance.org_id is None for instance in instances} == {True, False}


def test_the_cli_names_the_credentials_with_no_key_behind_them(tmp_path, monkeypatch):
    """Silent success reads as failure: the command already names an empty catalog, and a pool that
    reaches nothing until a key is supplied is the same kind of thing to say out loud.

    Run from a directory with no .env, because the command loads one from its working directory and
    a developer's would put a real key behind the credentials this is about.
    """
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    seed_catalog(tmp_path)
    monkeypatch.chdir(tmp_path)
    seeded = runner.invoke(cli_app, ["fixtures", "--config", cfg])

    assert seeded.exit_code == 0, seeded.output
    assert "openai" in seeded.output
    assert "invitations" in seeded.output
    assert "new.member@example.com" in seeded.output
