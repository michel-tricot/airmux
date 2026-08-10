"""Development fixtures seed a fresh instance only, and refuse a database that is already somebody's.

There is no merge and no partial reset, so this refusal is the whole contract worth holding: to
reseed, drop the database and recreate it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from helpers import run_in_db, setup_control_plane, write_config
from typer.testing import CliRunner

from contract import EnvStoreConfig, MemoryStoreConfig
from control_plane.fixtures import FIXTURE_PROVIDER_KEY, MissingProvidersError, NotAnEmptyDatabaseError, apply_fixtures
from control_plane.main import app as cli_app
from control_plane.models import Org, Provider, ProviderCredential, set_actor

runner = CliRunner()

CSRF = {"X-Requested-With": "fetch"}
NOW = datetime(2026, 8, 9, tzinfo=UTC)


def test_apply_refuses_a_database_that_already_holds_accounts(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        c.post("/v1/auth/signup", json={"email": "real@example.com", "password": "hunter2hunter2", "name": "Real"}, headers=CSRF)

    with pytest.raises(NotAnEmptyDatabaseError):
        run_in_db(tmp_path, lambda: apply_fixtures(NOW, MemoryStoreConfig().build()))

    assert run_in_db(tmp_path, Org.find) == []


def test_cli_refuses_a_database_that_is_not_empty(tmp_path):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    with TestClient(cp.app) as c:
        c.post("/v1/auth/signup", json={"email": "real@example.com", "password": "hunter2hunter2", "name": "Real"}, headers=CSRF)

    refused = runner.invoke(cli_app, ["fixtures", "--config", cfg])

    assert refused.exit_code == 1
    assert "not an empty database" in refused.output
    assert run_in_db(tmp_path, Org.find) == []


@pytest.fixture(autouse=True)
def _no_ambient_provider_keys(monkeypatch):
    """The env store reads the process environment, so a developer with OPENAI_API_KEY exported
    would otherwise get different results from these tests than CI does."""
    for provider in ("OPENAI", "ANTHROPIC"):
        monkeypatch.delenv(f"{provider}_API_KEY", raising=False)
        monkeypatch.delenv(f"AIRLLM_SECRET_PROVIDER_{provider}", raising=False)


def seed_catalog(tmp_path):
    """The providers the fixtures route traffic to, as `airllmcp taxonomy` would leave them."""

    async def apply():
        await set_actor("root")
        for name in ("openai", "anthropic"):
            await Provider(name=name, kind="openai_compatible", base_url=f"https://{name}.test/v1").save()

    run_in_db(tmp_path, apply)


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
