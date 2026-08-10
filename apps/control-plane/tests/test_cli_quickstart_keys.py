"""What quickstart does about provider keys, against a real control plane.

The command's own flow (signup, device authorization, dropping the data plane token) is covered
where those surfaces live. This is the part that decides whether a fresh install can serve a
request at all: an org with a catalog and no credential is a gateway that routes nothing.
"""

from __future__ import annotations

import asyncio

import typer
from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, make_org, setup_control_plane

from cli.auth import seed_provider_credentials
from contract import EnvStoreConfig, SecretPurpose, SecretRef

OPENAI_KEY = "sk-openai-from-the-operator-1111"
ANTHROPIC = {"provider_id": "anthropic", "kind": "anthropic", "base_url": "https://api.anthropic.com/v1"}


def _refuse_to_prompt(label, **_):
    msg = f"asked for {label} when it should not have"
    raise AssertionError(msg)


def stack(tmp_path, monkeypatch, secrets=None):
    """A claimed instance with a catalog and an org key, which is where quickstart is by then."""
    cp = setup_control_plane(tmp_path, secrets=secrets)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    client = TestClient(cp.app)
    client.__enter__()
    root = cp.headers()
    client.post("/v1/taxonomy/providers", json=PROVIDER, headers=root)
    client.post("/v1/taxonomy/providers", json=ANTHROPIC, headers=root)
    client.post("/v1/taxonomy/models", json=MODEL, headers=root)
    org = cp.headers(make_org(client, root))
    return cp, client, org


def stored(cp, credential: dict) -> str:
    ref = SecretRef(
        purpose=SecretPurpose.provider,
        service=credential["provider_name"],
        name=credential["name"],
        secret_id=credential["id"],
        org_id=credential["org_id"],
        workspace_id=credential["workspace_id"],
    )
    return asyncio.run(cp.app.state.secret_store.get(ref)).reveal()


def test_a_key_in_the_environment_becomes_an_org_credential(tmp_path, monkeypatch):
    """The reason quickstart looks: an operator who already exported OPENAI_API_KEY to use the
    provider directly should not have to learn a credential API before their first request."""
    cp, client, org = stack(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)

    seeded = seed_provider_credentials(client, org, {})

    assert [(k.provider, k.source) for k in seeded] == [("openai", "found in OPENAI_API_KEY")]
    credential = client.get("/v1/org/provider-credentials", headers=org).json()["data"][0]
    assert credential["scope"] == "org"
    assert credential["provider_name"] == "openai"
    assert stored(cp, credential) == OPENAI_KEY


def test_an_explicit_key_wins_over_the_environment(tmp_path, monkeypatch):
    cp, client, org = stack(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)

    seed_provider_credentials(client, org, {"openai": "sk-explicit-2222"})

    credential = client.get("/v1/org/provider-credentials", headers=org).json()["data"][0]
    assert stored(cp, credential) == "sk-explicit-2222"


def test_providers_without_a_key_are_left_alone(tmp_path, monkeypatch):
    """Seeding what it can beats refusing: a deployment that only uses openai should not have to
    supply an anthropic key to finish setting up."""
    _, client, org = stack(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)

    assert [k.provider for k in seed_provider_credentials(client, org, {})] == ["openai"]
    assert [c["provider_name"] for c in client.get("/v1/org/provider-credentials", headers=org).json()["data"]] == ["openai"]


def test_a_key_for_a_provider_outside_the_catalog_is_ignored(tmp_path, monkeypatch):
    """The catalog decides what exists; an unknown provider would only 404 the create."""
    _, client, org = stack(tmp_path, monkeypatch)

    assert seed_provider_credentials(client, org, {"nowhere": "sk-3333"}) == []


def test_an_env_backed_instance_records_the_key_it_already_has(tmp_path, monkeypatch):
    """The default deployment. Nothing is written: quickstart read the variable and the store
    resolves the same one, so storing it is a declaration that the org uses it."""
    cp, client, org = stack(tmp_path, monkeypatch, secrets=EnvStoreConfig())
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)

    assert [k.provider for k in seed_provider_credentials(client, org, {})] == ["openai"]
    credential = client.get("/v1/org/provider-credentials", headers=org).json()["data"][0]
    assert credential["scope"] == "org"
    assert stored(cp, credential) == OPENAI_KEY


def test_an_env_backed_instance_seeds_nothing_it_cannot_resolve(tmp_path, monkeypatch):
    """A key typed at the prompt cannot be honored by a store that only reads the environment, and
    quickstart has already created an account and an org; the command reports and carries on."""
    _, client, org = stack(tmp_path, monkeypatch, secrets=EnvStoreConfig())

    refused = seed_provider_credentials(client, org, {"openai": "sk-typed-not-exported"})

    assert [(k.provider, k.source) for k in refused] == [("openai", "given on the command line")]
    assert "OPENAI_API_KEY" in refused[0].error
    assert client.get("/v1/org/provider-credentials", headers=org).json()["data"] == []


def test_a_key_is_asked_for_when_the_environment_is_silent(tmp_path, monkeypatch):
    """An operator who never exported the variable has the key in front of them; making them leave
    the command to set one is the difference between a quickstart that serves and one that does not."""
    cp, client, org = stack(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = {"openai": "sk-typed-in-4444", "anthropic": ""}
    monkeypatch.setattr(typer, "prompt", lambda label, **_: next(v for k, v in answers.items() if k in label))

    assert [k.provider for k in seed_provider_credentials(client, org, {})] == ["openai"]
    assert stored(cp, client.get("/v1/org/provider-credentials", headers=org).json()["data"][0]) == "sk-typed-in-4444"


def test_a_blank_answer_with_nothing_exported_skips_the_provider(tmp_path, monkeypatch):
    """A provider the org does not use should not get a credential it cannot resolve."""
    _, client, org = stack(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(typer, "prompt", lambda label, **_: "")

    assert seed_provider_credentials(client, org, {}) == []


def test_nothing_is_asked_without_a_terminal(tmp_path, monkeypatch):
    """Quickstart runs in scripts and containers too, where a prompt is a hang rather than a question."""
    _, client, org = stack(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr(typer, "prompt", _refuse_to_prompt)

    assert seed_provider_credentials(client, org, {}) == []


def test_a_blank_answer_takes_the_exported_key(tmp_path, monkeypatch):
    """The common case, and one keystroke: the operator is still asked which providers this org
    spends against, and an exported variable is the answer they accept rather than one assumed."""
    cp, client, org = stack(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(typer, "prompt", lambda label, **_: "")

    assert [(k.provider, k.source) for k in seed_provider_credentials(client, org, {})] == [("openai", "found in OPENAI_API_KEY")]
    assert stored(cp, client.get("/v1/org/provider-credentials", headers=org).json()["data"][0]) == OPENAI_KEY


def test_the_prompt_says_which_variable_a_blank_answer_takes(tmp_path, monkeypatch):
    """Blank meaning two different things by provider is only safe if the prompt says which."""
    _, client, org = stack(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    asked = []
    monkeypatch.setattr(typer, "prompt", lambda label, **_: asked.append(label) or "")

    seed_provider_credentials(client, org, {})

    assert any("openai" in label and "blank to use OPENAI_API_KEY" in label for label in asked)
    assert any("anthropic" in label and "blank to skip" in label for label in asked)


def test_a_typed_key_wins_over_the_exported_one(tmp_path, monkeypatch):
    cp, client, org = stack(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(typer, "prompt", lambda label, **_: "sk-typed-5555" if "openai" in label else "")

    assert [(k.provider, k.source) for k in seed_provider_credentials(client, org, {})] == [("openai", "entered")]
    assert stored(cp, client.get("/v1/org/provider-credentials", headers=org).json()["data"][0]) == "sk-typed-5555"
