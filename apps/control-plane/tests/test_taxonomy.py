from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient
from helpers import run_in_db, run_init, setup_control_plane, write_config
from typer.testing import CliRunner

from control_plane.main import app
from control_plane.models import Bundle, Model, Org, Provider
from control_plane.taxonomy import TaxonomySpec, UnknownProviderError, apply_taxonomy

runner = CliRunner()

TAXONOMY = """
providers:
  - provider_id: stub
    base_url: https://stub.example/v1
    credential_ref: env:STUB_KEY
models:
  - model_id: echo
    provider_id: stub
"""


def test_empty_taxonomy_parses_to_defaults():
    spec = TaxonomySpec.model_validate(yaml.safe_load("{}"))
    assert spec.providers == []
    assert spec.models == []


def test_apply_taxonomy_upserts(tmp_path):
    setup_control_plane(tmp_path)
    spec = TaxonomySpec.model_validate(yaml.safe_load(TAXONOMY))
    assert run_in_db(tmp_path, lambda: apply_taxonomy(spec)) == (1, 1)
    changed = TaxonomySpec.model_validate(yaml.safe_load(TAXONOMY.replace("stub.example", "stub2.example")))
    assert run_in_db(tmp_path, lambda: apply_taxonomy(changed)) == (1, 1)
    providers = run_in_db(tmp_path, Provider.find)
    assert [p.base_url for p in providers] == ["https://stub2.example/v1"]
    assert len(run_in_db(tmp_path, Model.find)) == 1


def test_apply_taxonomy_rejects_a_model_with_an_unknown_provider(tmp_path):
    setup_control_plane(tmp_path)
    spec = TaxonomySpec.model_validate({"models": [{"model_id": "ghost", "provider_id": "nope"}]})
    with pytest.raises(UnknownProviderError):
        run_in_db(tmp_path, lambda: apply_taxonomy(spec))
    assert run_in_db(tmp_path, Model.find) == []


def test_taxonomy_command_applies_and_compiles(tmp_path):
    init = run_init(tmp_path, taxonomy=TAXONOMY)
    assert init.exit_code == 0, init.output
    tax_path = tmp_path / "taxonomy.yml"
    doc = yaml.safe_load(tax_path.read_text(encoding="utf-8"))
    doc["models"].append({"model_id": "echo-2", "provider_id": "stub"})
    tax_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    result = runner.invoke(app, ["taxonomy", "--config", str(tmp_path / "airllm.yml")])
    assert result.exit_code == 0, result.output
    models = run_in_db(tmp_path, Model.find)
    assert "echo-2" in {m.id for m in models}
    assert [b.version for b in run_in_db(tmp_path, Bundle.find)] == [1, 2]


def test_taxonomy_command_compiles_a_bundle_per_org(tmp_path):
    init = run_init(tmp_path, taxonomy=TAXONOMY)
    assert init.exit_code == 0, init.output
    run_in_db(tmp_path, lambda: Org(id="org-two", name="org-two").save())
    result = runner.invoke(app, ["taxonomy", "--config", str(tmp_path / "airllm.yml")])
    assert result.exit_code == 0, result.output
    bundles = run_in_db(tmp_path, Bundle.find)
    assert {b.org_id for b in bundles} == {"org-dev", "org-two"}


def test_taxonomy_command_applies_without_orgs(tmp_path):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    (tmp_path / "taxonomy.yml").write_text(TAXONOMY, encoding="utf-8")
    result = runner.invoke(app, ["taxonomy", "--config", cfg])
    assert result.exit_code == 0, result.output
    assert [p.id for p in run_in_db(tmp_path, Provider.find)] == ["stub"]
    assert run_in_db(tmp_path, Bundle.find) == []


def test_serve_does_not_seed(tmp_path):
    cp = setup_control_plane(tmp_path)
    (tmp_path / "taxonomy.yml").write_text(TAXONOMY, encoding="utf-8")
    with TestClient(cp.app) as c:
        assert c.get("/v1/instance/orgs", headers=cp.headers()).json()["data"] == []
    assert run_in_db(tmp_path, Org.find) == []
