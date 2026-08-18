from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from helpers import run_in_db, setup_control_plane, setup_db, write_config
from typer.testing import CliRunner

import control_plane
from control_plane.main import app
from control_plane.models import AuditLog, Bundle, Model, Org, Provider, set_actor
from control_plane.taxonomy import TaxonomySpec, UnknownProviderError, apply_taxonomy

runner = CliRunner()

REPO_ROOT = Path(control_plane.__file__).resolve().parents[4]

TAXONOMY = """
providers:
  - provider_id: stub
    base_url: https://stub.example/v1
models:
  - model_id: echo
    provider_id: stub
"""

STUB_ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>'

TAXONOMY_WITH_ICON = f"""
providers:
  - provider_id: stub
    base_url: https://stub.example/v1
    icon: '{STUB_ICON}'
"""


def test_empty_taxonomy_parses_to_defaults():
    spec = TaxonomySpec.model_validate(yaml.safe_load("{}"))
    assert spec.providers == []
    assert spec.models == []


def test_apply_taxonomy_upserts(tmp_path):
    setup_db(tmp_path)

    async def apply(doc: str):
        await set_actor("u-test")
        return await apply_taxonomy(TaxonomySpec.model_validate(yaml.safe_load(doc)))

    assert run_in_db(tmp_path, lambda: apply(TAXONOMY)) == (1, 1)
    assert run_in_db(tmp_path, lambda: apply(TAXONOMY.replace("stub.example", "stub2.example"))) == (1, 1)
    providers = run_in_db(tmp_path, Provider.find)
    assert [p.base_url for p in providers] == ["https://stub2.example/v1"]
    assert len(run_in_db(tmp_path, Model.find)) == 1


def test_apply_taxonomy_carries_the_provider_icon(tmp_path):
    setup_db(tmp_path)

    async def apply(doc: str):
        await set_actor("u-test")
        return await apply_taxonomy(TaxonomySpec.model_validate(yaml.safe_load(doc)))

    run_in_db(tmp_path, lambda: apply(TAXONOMY_WITH_ICON))
    assert [p.icon for p in run_in_db(tmp_path, Provider.find)] == [STUB_ICON]

    replaced = STUB_ICON.replace("M0 0h24v24H0z", "M1 1h22v22H1z")
    run_in_db(tmp_path, lambda: apply(TAXONOMY_WITH_ICON.replace(STUB_ICON, replaced)))
    assert [p.icon for p in run_in_db(tmp_path, Provider.find)] == [replaced]


TAXONOMY_WITH_PROFILE = """
providers:
  - provider_id: stub
    base_url: https://stub.example/v1
    param_aliases:
      max_tokens: max_completion_tokens
    accepted_params: [top_k]
    params_closed: true
"""


def test_apply_taxonomy_carries_the_provider_profile(tmp_path):
    """The profile is what makes onboarding a quirky provider a config change; losing it on
    upsert would silently reopen a closed schema."""
    setup_db(tmp_path)

    async def apply(doc: str):
        await set_actor("u-test")
        return await apply_taxonomy(TaxonomySpec.model_validate(yaml.safe_load(doc)))

    run_in_db(tmp_path, lambda: apply(TAXONOMY_WITH_PROFILE))
    (provider,) = run_in_db(tmp_path, Provider.find)
    assert provider.param_aliases == {"max_tokens": "max_completion_tokens"}
    assert provider.accepted_params == ["top_k"]
    assert provider.params_closed is True

    run_in_db(tmp_path, lambda: apply(TAXONOMY))
    (provider,) = run_in_db(tmp_path, Provider.find)
    assert provider.param_aliases == {}
    assert provider.accepted_params is None
    assert provider.params_closed is False


def test_apply_taxonomy_carries_direct_model_prices(tmp_path):
    setup_db(tmp_path)
    spec = TaxonomySpec.model_validate(
        yaml.safe_load(
            """
providers:
  - provider_id: stub
    base_url: https://stub.example/v1
models:
  - model_id: echo
    provider_id: stub
    input_price_per_mtok: 2.0
    output_price_per_mtok: 5.0
    cache_read_price_per_mtok: 0.25
    cache_write_price_per_mtok: 2.5
"""
        )
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
    ) == (2.0, 5.0, 0.25, 2.5)


def test_a_provider_declaring_no_icon_has_none(tmp_path):
    setup_db(tmp_path)

    async def apply():
        await set_actor("u-test")
        return await apply_taxonomy(TaxonomySpec.model_validate(yaml.safe_load(TAXONOMY)))

    run_in_db(tmp_path, apply)
    assert [p.icon for p in run_in_db(tmp_path, Provider.find)] == [""]


def test_every_shipped_provider_carries_a_square_icon():
    """The icons are data, so the guard is on the file the instance actually applies."""
    spec = TaxonomySpec.model_validate(yaml.safe_load((REPO_ROOT / "taxonomy" / "taxonomy.yml").read_text(encoding="utf-8")))
    assert spec.providers != []
    for provider in spec.providers:
        assert provider.icon.startswith("<svg "), provider.provider_id
        assert provider.icon.endswith("</svg>"), provider.provider_id
        assert 'viewBox="0 0 24 24"' in provider.icon, provider.provider_id


def test_shipped_taxonomy_prices_each_model_directly():
    taxonomy = yaml.safe_load((REPO_ROOT / "taxonomy" / "taxonomy.yml").read_text(encoding="utf-8"))
    price_fields = {
        "input_price_per_mtok",
        "output_price_per_mtok",
        "cache_read_price_per_mtok",
        "cache_write_price_per_mtok",
    }
    for provider in taxonomy["providers"]:
        assert "cache_read_multiplier" not in provider
        assert "cache_write_multiplier" not in provider
    for model in taxonomy["models"]:
        assert price_fields <= model.keys(), model["model_id"]


def test_apply_taxonomy_rejects_a_model_with_an_unknown_provider(tmp_path):
    setup_db(tmp_path)
    spec = TaxonomySpec.model_validate({"models": [{"model_id": "ghost", "provider_id": "nope"}]})

    async def apply():
        await set_actor("u-test")
        return await apply_taxonomy(spec)

    with pytest.raises(UnknownProviderError):
        run_in_db(tmp_path, apply)
    assert run_in_db(tmp_path, Model.find) == []


def _seed_orgs(tmp_path, *names: str) -> None:
    async def seed() -> None:
        await set_actor("root")
        for name in names:
            await Org.create(name)

    run_in_db(tmp_path, seed)


def test_taxonomy_command_applies_and_compiles(tmp_path):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    _seed_orgs(tmp_path, "org-dev")
    tax_path = tmp_path / "taxonomy.yml"
    tax_path.write_text(TAXONOMY, encoding="utf-8")
    assert runner.invoke(app, ["taxonomy", "--config", cfg]).exit_code == 0
    doc = yaml.safe_load(tax_path.read_text(encoding="utf-8"))
    doc["models"].append({"model_id": "echo-2", "provider_id": "stub"})
    tax_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    result = runner.invoke(app, ["taxonomy", "--config", cfg])
    assert result.exit_code == 0, result.output
    models = run_in_db(tmp_path, Model.find)
    assert "echo-2" in {m.name for m in models}
    assert [b.version for b in run_in_db(tmp_path, Bundle.find)] == [1, 2]


def test_taxonomy_command_compiles_a_bundle_per_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    _seed_orgs(tmp_path, "org-one", "org-two")
    (tmp_path / "taxonomy.yml").write_text(TAXONOMY, encoding="utf-8")
    result = runner.invoke(app, ["taxonomy", "--config", cfg])
    assert result.exit_code == 0, result.output
    bundles = run_in_db(tmp_path, Bundle.find)
    orgs = run_in_db(tmp_path, Org.find)
    assert {b.org_id for b in bundles} == {o.id for o in orgs}


def test_taxonomy_command_seeds_a_virgin_database_as_root(tmp_path):
    """The docker startup chain seeds before any admin exists; the writes are attributed to root."""
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    (tmp_path / "taxonomy.yml").write_text(TAXONOMY, encoding="utf-8")
    result = runner.invoke(app, ["taxonomy", "--config", cfg])
    assert result.exit_code == 0, result.output
    assert [p.name for p in run_in_db(tmp_path, Provider.find)] == ["stub"]
    assert {entry.user_id for entry in run_in_db(tmp_path, AuditLog.find)} == {"root"}


def test_taxonomy_command_applies_without_orgs(tmp_path):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    (tmp_path / "taxonomy.yml").write_text(TAXONOMY, encoding="utf-8")
    result = runner.invoke(app, ["taxonomy", "--config", cfg])
    assert result.exit_code == 0, result.output
    assert [p.name for p in run_in_db(tmp_path, Provider.find)] == ["stub"]
    assert run_in_db(tmp_path, Bundle.find) == []


def test_serve_does_not_seed(tmp_path):
    cp = setup_control_plane(tmp_path)
    (tmp_path / "taxonomy.yml").write_text(TAXONOMY, encoding="utf-8")
    with TestClient(cp.app) as c:
        assert c.get("/api/v1/orgs", headers=cp.headers()).json()["data"] == []
    assert run_in_db(tmp_path, Org.find) == []
