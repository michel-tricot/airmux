from __future__ import annotations

from decimal import Decimal

import pytest
import yaml
from fastapi.testclient import TestClient
from helpers import run_in_db, setup_control_plane, setup_db, write_config
from typer.testing import CliRunner

from airmux_runtime.taxonomy import load_taxonomy
from cli.control_plane import control_plane_app as app
from contract.taxonomy import TaxonomySpec
from control_plane.models import AuditLog, Bundle, GlobalRuntimeConfiguration, Model, Org, Provider, RuntimeConfiguration, set_actor
from control_plane.taxonomy import UnknownProviderError, apply_taxonomy

runner = CliRunner()


TAXONOMY = """
providers:
  - provider_id: stub
    base_url: https://stub.example/v1
models:
  - model_id: echo
    provider_id: stub
    input_modalities: [text]
    output_modalities: [text]
"""


STUB_ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>'


TAXONOMY_WITH_ICON = f"""
providers:
  - provider_id: stub
    base_url: https://stub.example/v1
    icon: '{STUB_ICON}'
"""


TAXONOMY_WITH_PROFILE = """
providers:
  - provider_id: stub
    base_url: https://stub.example/v1
    param_aliases:
      max_output_tokens: max_completion_tokens
    accepted_params: [top_k]
    params_closed: true
"""


def _seed_orgs(tmp_path, *names: str) -> None:
    async def seed() -> None:
        await set_actor("root")
        for name in names:
            await Org.create(name)

    run_in_db(tmp_path, seed)


def test_apply_taxonomy_upserts(tmp_path):
    setup_db(tmp_path)

    async def apply(doc: str):
        await set_actor("u-test")
        return await apply_taxonomy(load_taxonomy(doc))

    assert run_in_db(tmp_path, lambda: apply(TAXONOMY)) == (1, 1)
    assert run_in_db(tmp_path, lambda: apply(TAXONOMY.replace("stub.example", "stub2.example"))) == (1, 1)
    providers = run_in_db(tmp_path, Provider.find)
    assert [p.base_url for p in providers] == ["https://stub2.example/v1"]
    assert len(run_in_db(tmp_path, Model.find)) == 1


def test_apply_taxonomy_carries_the_provider_icon(tmp_path):
    setup_db(tmp_path)

    async def apply(doc: str):
        await set_actor("u-test")
        return await apply_taxonomy(load_taxonomy(doc))

    run_in_db(tmp_path, lambda: apply(TAXONOMY_WITH_ICON))
    assert [p.icon for p in run_in_db(tmp_path, Provider.find)] == [STUB_ICON]

    replaced = STUB_ICON.replace("M0 0h24v24H0z", "M1 1h22v22H1z")
    run_in_db(tmp_path, lambda: apply(TAXONOMY_WITH_ICON.replace(STUB_ICON, replaced)))
    assert [p.icon for p in run_in_db(tmp_path, Provider.find)] == [replaced]


def test_apply_taxonomy_carries_the_provider_profile(tmp_path):
    """The profile is what makes onboarding a quirky provider a config change; losing it on
    upsert would silently reopen a closed schema."""
    setup_db(tmp_path)

    async def apply(doc: str):
        await set_actor("u-test")
        return await apply_taxonomy(load_taxonomy(doc))

    run_in_db(tmp_path, lambda: apply(TAXONOMY_WITH_PROFILE))
    (provider,) = run_in_db(tmp_path, Provider.find)
    assert provider.param_aliases == {"max_output_tokens": "max_completion_tokens"}
    assert provider.accepted_params == ["top_k"]
    assert provider.params_closed is True

    run_in_db(tmp_path, lambda: apply(TAXONOMY))
    (provider,) = run_in_db(tmp_path, Provider.find)
    assert provider.param_aliases == {}
    assert provider.accepted_params is None
    assert provider.params_closed is False


def test_apply_taxonomy_carries_direct_model_prices(tmp_path):
    setup_db(tmp_path)
    spec = load_taxonomy(
        """
providers:
  - provider_id: stub
    base_url: https://stub.example/v1
models:
  - model_id: echo
    provider_id: stub
    input_modalities: [text]
    output_modalities: [text]
    input_price_per_mtok: 2.0
    output_price_per_mtok: 5.0
    cache_read_price_per_mtok: 0.25
    cache_write_price_per_mtok: 2.5
"""
    )

    async def apply():
        await set_actor("u-test")
        return await apply_taxonomy(spec)

    run_in_db(tmp_path, apply)
    (model,) = run_in_db(tmp_path, Model.find)
    assert (
        model.input_price_per_mtok,
        model.output_price_per_mtok,
        model.cache_read_price_per_mtok,
        model.cache_write_price_per_mtok,
    ) == (Decimal("2.0"), Decimal("5.0"), Decimal("0.25"), Decimal("2.5"))


def test_apply_taxonomy_carries_model_parameter_support(tmp_path):
    setup_db(tmp_path)
    spec = load_taxonomy(
        """
providers:
  - provider_id: stub
    base_url: https://stub.example/v1
models:
  - model_id: echo
    provider_id: stub
    input_modalities: [text]
    output_modalities: [text]
    parameter_support:
      temperature: unsupported
"""
    )

    async def apply():
        await set_actor("u-test")
        return await apply_taxonomy(spec)

    run_in_db(tmp_path, apply)
    (model,) = run_in_db(tmp_path, Model.find)
    assert model.parameter_support == {"temperature": "unsupported"}


def test_apply_taxonomy_carries_model_modalities(tmp_path):
    setup_db(tmp_path)
    spec = load_taxonomy(
        """
providers:
  - provider_id: stub
    base_url: https://stub.example/v1
models:
  - model_id: echo
    provider_id: stub
    input_modalities: [text, image]
    output_modalities: [text]
"""
    )

    async def apply():
        await set_actor("u-test")
        return await apply_taxonomy(spec)

    run_in_db(tmp_path, apply)
    (model,) = run_in_db(tmp_path, Model.find)
    assert model.input_modalities == ["text", "image"]
    assert model.output_modalities == ["text"]


def test_a_provider_declaring_no_icon_has_none(tmp_path):
    setup_db(tmp_path)

    async def apply():
        await set_actor("u-test")
        return await apply_taxonomy(load_taxonomy(TAXONOMY))

    run_in_db(tmp_path, apply)
    assert [p.icon for p in run_in_db(tmp_path, Provider.find)] == [""]


def test_apply_taxonomy_rejects_a_model_with_an_unknown_provider(tmp_path):
    setup_db(tmp_path)
    spec = TaxonomySpec.model_validate(
        {"models": [{"model_id": "ghost", "provider_id": "nope", "input_modalities": ["text"], "output_modalities": ["text"]}]}
    )

    async def apply():
        await set_actor("u-test")
        return await apply_taxonomy(spec)

    with pytest.raises(UnknownProviderError):
        run_in_db(tmp_path, apply)
    assert run_in_db(tmp_path, Model.find) == []


def test_taxonomy_command_applies_and_queues_publication(tmp_path):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    _seed_orgs(tmp_path, "org-dev")
    tax_path = tmp_path / "taxonomy.yml"
    tax_path.write_text(TAXONOMY, encoding="utf-8")
    assert runner.invoke(app, ["taxonomy", "--file", "taxonomy.yml", "--config", cfg]).exit_code == 0
    doc = yaml.safe_load(tax_path.read_text(encoding="utf-8"))
    doc["models"].append({"model_id": "echo-2", "provider_id": "stub", "input_modalities": ["text"], "output_modalities": ["text"]})
    tax_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    result = runner.invoke(app, ["taxonomy", "--file", "taxonomy.yml", "--config", cfg])
    assert result.exit_code == 0, result.output
    models = run_in_db(tmp_path, Model.find)
    assert "echo-2" in {m.name for m in models}
    assert run_in_db(tmp_path, Bundle.find) == []
    assert run_in_db(tmp_path, GlobalRuntimeConfiguration.desired) == 2


def test_taxonomy_command_records_one_global_revision_for_every_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    _seed_orgs(tmp_path, "org-one", "org-two")
    (tmp_path / "taxonomy.yml").write_text(TAXONOMY, encoding="utf-8")
    result = runner.invoke(app, ["taxonomy", "--file", "taxonomy.yml", "--config", cfg])
    assert result.exit_code == 0, result.output
    assert run_in_db(tmp_path, Bundle.find) == []
    assert run_in_db(tmp_path, RuntimeConfiguration.find) == []
    assert run_in_db(tmp_path, GlobalRuntimeConfiguration.desired) == 1


def test_taxonomy_command_seeds_a_virgin_database_as_root(tmp_path):
    """The docker startup chain seeds before any admin exists; the writes are attributed to root."""
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    (tmp_path / "taxonomy.yml").write_text(TAXONOMY, encoding="utf-8")
    result = runner.invoke(app, ["taxonomy", "--file", "taxonomy.yml", "--config", cfg])
    assert result.exit_code == 0, result.output
    assert [p.name for p in run_in_db(tmp_path, Provider.find)] == ["stub"]
    assert {entry.user_id for entry in run_in_db(tmp_path, AuditLog.find)} == {"root"}


def test_taxonomy_command_applies_without_orgs(tmp_path):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    (tmp_path / "taxonomy.yml").write_text(TAXONOMY, encoding="utf-8")
    result = runner.invoke(app, ["taxonomy", "--file", "taxonomy.yml", "--config", cfg])
    assert result.exit_code == 0, result.output
    assert [p.name for p in run_in_db(tmp_path, Provider.find)] == ["stub"]
    assert run_in_db(tmp_path, Bundle.find) == []


def test_serve_does_not_seed(tmp_path):
    cp = setup_control_plane(tmp_path)
    (tmp_path / "taxonomy.yml").write_text(TAXONOMY, encoding="utf-8")
    with TestClient(cp.app) as c:
        assert c.get("/api/v1/organizations", headers=cp.headers()).json()["data"] == []
    assert run_in_db(tmp_path, Org.find) == []
