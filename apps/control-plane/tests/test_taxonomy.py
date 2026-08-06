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

    async def first_apply():
        await Org(id="o1", name="o1").save()
        return await apply_taxonomy(spec, "o1")

    assert run_in_db(tmp_path, first_apply) == (1, 1)
    changed = TaxonomySpec.model_validate(yaml.safe_load(TAXONOMY.replace("stub.example", "stub2.example")))
    assert run_in_db(tmp_path, lambda: apply_taxonomy(changed, "o1")) == (1, 1)
    providers = run_in_db(tmp_path, Provider.find)
    assert [p.base_url for p in providers] == ["https://stub2.example/v1"]
    assert len(run_in_db(tmp_path, Model.find)) == 1


def test_apply_taxonomy_rejects_a_model_with_an_unknown_provider(tmp_path):
    setup_control_plane(tmp_path)
    spec = TaxonomySpec.model_validate({"models": [{"model_id": "ghost", "provider_id": "nope"}]})

    async def apply():
        await Org(id="o1", name="o1").save()
        return await apply_taxonomy(spec, "o1")

    with pytest.raises(UnknownProviderError):
        run_in_db(tmp_path, apply)
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


def test_taxonomy_command_requires_an_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    cfg = write_config(tmp_path, cp)
    (tmp_path / "taxonomy.yml").write_text(TAXONOMY, encoding="utf-8")
    result = runner.invoke(app, ["taxonomy", "--config", cfg])
    assert result.exit_code == 1


def test_serve_does_not_seed(tmp_path):
    cp = setup_control_plane(tmp_path)
    (tmp_path / "taxonomy.yml").write_text(TAXONOMY, encoding="utf-8")
    with TestClient(cp.app) as c:
        assert c.get("/instance/orgs", headers=cp.headers()).json() == []
    assert run_in_db(tmp_path, Org.find) == []
