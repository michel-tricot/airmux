from __future__ import annotations

import json
import shutil
import urllib.error
from http.client import HTTPMessage
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from model_audit import cli
from model_audit.catalog_ops import ProviderDefinition, add_provider
from model_audit.catalog_tasks import (
    bootstrap,
    build_report,
    discover_parameters,
    doc_schemas,
    enrich,
    extract_schemas,
    fetch_icons,
    fetch_models,
    field_matrix,
    make_seed,
    validate,
)
from model_audit.catalog_tasks.outcomes import (
    CatalogValidated,
    ExtractedSchema,
    FetchedModels,
    ModelFetchFailed,
    SchemaFetchFailed,
    SkippedModels,
    UnknownProvidersError,
    ValidationFailed,
)
from model_audit.catalog_tasks.sources.base import GenericModelSource

ROOT = Path(__file__).parents[2]


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    taxonomy = tmp_path / "taxonomy"
    taxonomy.mkdir()
    (taxonomy / "models").mkdir()
    (tmp_path / "model-audit" / "catalog").mkdir(parents=True)
    for module in (
        bootstrap,
        build_report,
        discover_parameters,
        doc_schemas,
        enrich,
        extract_schemas,
        fetch_icons,
        fetch_models,
        field_matrix,
        make_seed,
    ):
        monkeypatch.setattr(module, "TAXONOMY", taxonomy)
    for module in (fetch_icons, fetch_models, field_matrix, validate):
        monkeypatch.setattr(module, "ROOT", taxonomy)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(fetch_models, "OUT", taxonomy / "models")
    monkeypatch.setattr(fetch_icons, "OUT", taxonomy / "icons")
    monkeypatch.setattr(doc_schemas, "OUT", taxonomy / "schemas" / "completion")
    monkeypatch.setattr(extract_schemas, "OUT", taxonomy / "schemas" / "completion")
    monkeypatch.setattr(field_matrix, "OUT", taxonomy / "reports")
    monkeypatch.setattr(make_seed, "SEED", tmp_path / "model-audit" / "catalog" / "seed.yml")
    monkeypatch.setattr(bootstrap, "SEED", make_seed.SEED)
    monkeypatch.setattr(validate, "SEED", make_seed.SEED)
    monkeypatch.setattr(fetch_models, "registry", dict)
    monkeypatch.setattr(cli, "provider_sources", dict)
    monkeypatch.delenv("STUB_API_KEY", raising=False)
    providers = [{"id": "stub", "models_url": "https://stub.example/models", "env_var": "STUB_API_KEY", "auth": ["bearer"]}]
    (taxonomy / "providers.yml").write_text(yaml.safe_dump({"providers": providers}))
    return taxonomy


@pytest.fixture
def ready_catalog(catalog, monkeypatch):
    definition = ProviderDefinition(
        id="stub",
        name="Stub",
        homepage="https://stub.example",
        docs="https://stub.example/docs",
        base_url="https://stub.example/v1",
        models_url="https://stub.example/models",
        ingress=("oai",),
        primary_surface="oai",
        auth=("bearer",),
        env_var="STUB_API_KEY",
    )
    add_provider(catalog.parent, definition, replace=True)
    schema_path = catalog / "schemas" / "completion" / "oai.stub.request.json"
    schema_path.parent.mkdir(parents=True)
    schema_path.write_text(json.dumps({"type": "object", "properties": {"temperature": {"type": "number"}}}))
    provider_path = catalog / "providers.yml"
    document = yaml.safe_load(provider_path.read_text())
    document["providers"][0]["schema"] = {"completion": {"oai": {"request": "schemas/completion/oai.stub.request.json"}}}
    provider_path.write_text(yaml.safe_dump(document))
    (catalog / "model-routes.yml").write_text("models: {}\n")
    for name in ("cases", "definitions"):
        shutil.copytree(ROOT / "model-audit" / name, catalog.parent / "model-audit" / name)
    monkeypatch.setenv("STUB_API_KEY", "test-key")
    monkeypatch.setattr(
        GenericModelSource,
        "fetch",
        lambda self, key: {"data": [{"id": "model", "context_length": 8192, "input_modalities": ["text"], "output_modalities": ["text"]}]},
    )
    monkeypatch.setattr(
        enrich,
        "get",
        lambda url: (
            {"stub": {"models": {"model": {"limit": {"context": 9999, "output": 1024}, "cost": {"input": 1, "output": 2}}}}}
            if url == enrich.MODELS_DEV
            else {"data": []}
        ),
    )
    return catalog


def test_seed_operation_returns_counts_without_terminal_output(catalog, capsys):
    result = make_seed.run()

    assert [(count.kind, count.entries) for count in result.counts] == [("providers", 1)]
    assert yaml.safe_load(result.path.read_text())["providers"][0]["id"] == "stub"
    assert capsys.readouterr() == ("", "")


def test_unknown_model_selection_is_a_domain_error(catalog):
    with pytest.raises(UnknownProvidersError) as raised:
        discover_parameters.run(("unknown",))

    assert raised.value.providers == ("unknown",)
    assert raised.value.location == "taxonomy/models"


def test_model_skips_distinguish_selected_from_best_effort_acquisition(catalog, capsys):
    all_models = fetch_models.run()
    selected_models = fetch_models.run(("stub",))

    assert all_models.results == selected_models.results == (SkippedModels("stub", "no STUB_API_KEY in environment"),)
    assert not all_models.failed
    assert selected_models.failed
    assert list((catalog / "models").iterdir()) == []
    assert capsys.readouterr() == ("", "")


def test_documented_schemas_return_structured_outcomes(catalog, capsys):
    result = doc_schemas.run(("deepseek",))

    assert len(result.schemas) == 1
    schema = result.schemas[0]
    assert schema.name == "oai.deepseek.request"
    document = json.loads((catalog / "schemas" / "completion" / f"{schema.name}.json").read_text())
    assert schema.properties == len(document["properties"])
    assert schema.required == tuple(document["required"])
    assert capsys.readouterr() == ("", "")


def test_provider_sync_stops_after_a_required_model_skip(catalog):
    result = CliRunner().invoke(cli.app, ["providers", "sync", "stub", "--only", "models", "--format", "json"])

    assert result.exit_code == 1
    assert result.stderr == ""
    assert json.loads(result.stdout) == [
        {
            "provider": "stub",
            "component": "models",
            "status": "failed",
            "detail": "skip    stub          no STUB_API_KEY in environment; 0 written, 1 skipped, 0 failed",
        }
    ]
    assert not (catalog / "reports").exists()


def test_provider_sync_reports_seed_io_errors_as_json(catalog):
    make_seed.SEED.mkdir()

    result = CliRunner().invoke(cli.app, ["providers", "sync", "stub", "--only", "models", "--format", "json"])

    assert result.exit_code == 1
    (failure,) = json.loads(result.stdout)
    assert (failure["component"], failure["status"]) == ("seed", "failed")
    assert "IsADirectoryError" in failure["detail"]


@pytest.mark.parametrize("component", ["models", "pricing"])
def test_model_and_pricing_sync_replace_stale_enrichment_and_build_taxonomy(ready_catalog, component):
    model_path = ready_catalog / "models" / "stub.json"
    model_path.write_text(json.dumps({"models": [{"id": "model", "context_length": 1, "pricing": {"input_per_mtok": 999}}]}))

    result = CliRunner().invoke(cli.app, ["providers", "sync", "stub", "--only", component, "--format", "json"])

    assert result.exit_code == 0, result.output
    steps = json.loads(result.stdout)
    assert [step["component"] for step in steps] == [
        "models",
        "pricing",
        *(["parameters"] if component == "models" else []),
        "taxonomy",
        "validation",
    ]
    assert {step["status"] for step in steps} == {"completed"}
    (model,) = json.loads(model_path.read_text())["models"]
    assert model["context_length"] == 8192
    assert model["max_output_tokens"] == 1024
    assert model["pricing"] == {"input_per_mtok": 1, "output_per_mtok": 2}
    assert model["parameter_evidence"]["model_discovery"]["support"]["chat/completions"]["temperature"] == "supported"
    assert (ready_catalog / "taxonomy.yml").exists()


def test_sync_all_continues_after_one_provider_fails_and_validates(ready_catalog, monkeypatch):
    provider_path = ready_catalog / "providers.yml"
    document = yaml.safe_load(provider_path.read_text())
    document["providers"].append({**document["providers"][0], "id": "broken", "env_var": "BROKEN_API_KEY"})
    provider_path.write_text(yaml.safe_dump(document))
    monkeypatch.delenv("BROKEN_API_KEY", raising=False)

    result = CliRunner().invoke(cli.app, ["providers", "sync", "--only", "models", "--format", "json"])

    assert result.exit_code == 1
    steps = json.loads(result.stdout)
    assert (steps[0]["provider"], steps[0]["component"], steps[0]["status"]) == ("broken", "models", "failed")
    assert steps[-1]["provider"] == "all"
    assert steps[-1]["component"] == "validation"
    assert steps[-1]["status"] == "completed"
    assert json.loads((ready_catalog / "models" / "stub.json").read_text())["models"][0]["max_output_tokens"] == 1024


def test_acquisition_keeps_successes_when_another_provider_fails(ready_catalog, monkeypatch, capsys):
    provider_path = ready_catalog / "providers.yml"
    document = yaml.safe_load(provider_path.read_text())
    document["providers"].append({**document["providers"][0], "id": "broken"})
    provider_path.write_text(yaml.safe_dump(document))

    def fetch(source, key):
        return (
            {"data": []}
            if source.provider_id == "broken"
            else {"data": [{"id": "model", "input_modalities": ["text"], "output_modalities": ["text"]}]}
        )

    monkeypatch.setattr(GenericModelSource, "fetch", fetch)

    result = fetch_models.run()

    assert result.failed
    assert result.results == (ModelFetchFailed("broken", "empty or unrecognized payload"), FetchedModels("stub", 1, 0, 1))
    assert (ready_catalog / "models" / "stub.json").exists()
    assert not (ready_catalog / "models" / "broken.json").exists()
    assert capsys.readouterr() == ("", "")


def test_schema_fetch_failures_remain_nonfatal_diagnostics(catalog, monkeypatch, capsys):
    monkeypatch.setattr(extract_schemas, "SPECS", {("stub", "oai"): ("https://stub.example/spec", "/chat/completions")})
    monkeypatch.setattr(extract_schemas, "registry", dict)

    def unavailable(url):
        message = "offline"
        raise OSError(message)

    monkeypatch.setattr(extract_schemas, "fetch", unavailable)

    result = extract_schemas.run(("stub",))

    assert result.schemas == (SchemaFetchFailed("stub", "oai", "offline"),)
    assert not cli.catalog_output.failed(result)
    assert capsys.readouterr() == ("", "")


def test_schema_extraction_reports_written_parts(catalog, monkeypatch, capsys):
    monkeypatch.setattr(extract_schemas, "SPECS", {("stub", "oai"): ("https://stub.example/spec", "/chat/completions")})
    monkeypatch.setattr(extract_schemas, "registry", dict)
    schema = {"type": "object", "properties": {"temperature": {"type": "number"}}}
    document = {"paths": {"/chat/completions": {"post": {"requestBody": {"content": {"application/json": {"schema": schema}}}}}}}
    monkeypatch.setattr(extract_schemas, "fetch", lambda url: document)

    result = extract_schemas.run(("stub",))

    (acquired,) = result.schemas
    assert isinstance(acquired, ExtractedSchema)
    (request,) = acquired.parts
    path = catalog / "schemas" / "completion" / "oai.stub.request.json"
    assert request.kind == "request"
    assert request.size_bytes == path.stat().st_size
    assert json.loads(path.read_text())["properties"] == schema["properties"]
    assert capsys.readouterr() == ("", "")


def test_field_reports_return_paths_and_counts_without_printing(ready_catalog, capsys):
    schema = ready_catalog / "schemas" / "completion" / "airmux.request.yaml"
    schema.write_text("type: object\nproperties:\n  temperature:\n    type: number\n")

    oai = field_matrix.run("oai")
    anthropic = field_matrix.run("anthropic")
    report = build_report.run()

    assert (oai.columns, oai.paths, oai.universal) == (2, 1, 1)
    assert (anthropic.columns, anthropic.paths) == (1, 1)
    assert oai.csv_path.read_text().splitlines()[1] == "$.temperature,2,1,1,1"
    assert report.size_bytes == report.path.stat().st_size
    assert "__DATA__" not in report.path.read_text()
    assert "$.temperature" in report.path.read_text()
    assert capsys.readouterr() == ("", "")


def test_icons_keep_monograms_and_report_partial_failure(catalog, monkeypatch, capsys):
    (catalog / "providers.yml").write_text(yaml.safe_dump({"providers": [{"id": "stub", "icon_mono": "mono", "icon_color": "color"}]}))

    def unavailable(url, headers, *, timeout):
        raise urllib.error.HTTPError(url, 404 if url.endswith("mono.svg") else 503, "unavailable", HTTPMessage(), None)

    monkeypatch.setattr(fetch_icons, "fetch_text", unavailable)

    result = fetch_icons.run(("stub",))

    assert result.generated == ("mono",)
    assert result.failures == (("color", "HTTP 503"),)
    assert (catalog / "icons" / "mono.svg").read_text() == fetch_icons.monogram("mono")
    assert cli.catalog_output.failed(result)
    assert capsys.readouterr() == ("", "")


def test_validation_does_not_retain_failures_between_operations(ready_catalog, capsys):
    make_seed.run()
    fetch_models.run()
    enrich.run()
    cli.write_taxonomy(ready_catalog.parent)
    icon_path = ready_catalog / "icons" / "stub.svg"
    icon = icon_path.read_text()
    icon_path.unlink()

    failure = validate.run()
    icon_path.write_text(icon)
    success = validate.run()

    assert isinstance(failure, ValidationFailed)
    assert any("stub.svg" in problem for problem in failure.problems)
    assert isinstance(success, CatalogValidated)
    assert success.models == 1
    assert capsys.readouterr() == ("", "")


def test_validation_cli_renders_problems_and_exits_nonzero(ready_catalog):
    make_seed.run()
    fetch_models.run()
    enrich.run()
    cli.write_taxonomy(ready_catalog.parent)
    (ready_catalog / "icons" / "stub.svg").unlink()

    result = CliRunner().invoke(cli.app, ["taxonomy", "validate"])

    assert result.exit_code == 1
    assert "problems\n" in result.stdout
    assert "stub.svg, which is not in taxonomy/icons" in result.stdout
    assert "stub.svg, which is not in taxonomy/icons" in result.stderr
    assert "Traceback" not in result.output


def test_rebuild_preserves_readme_and_stops_at_missing_schema_executable(ready_catalog, monkeypatch):
    make_seed.run()
    source = GenericModelSource()
    definition = yaml.safe_load((ready_catalog / "providers.yml").read_text())["providers"][0]
    source.definition = ProviderDefinition.model_validate({key: value for key, value in definition.items() if key != "schema"})
    monkeypatch.setattr(bootstrap, "registry", lambda: {"stub": source})
    monkeypatch.setattr(cli.sys, "executable", str(ready_catalog.parent / "missing-python"))
    (ready_catalog / "README.md").write_text("catalog documentation\n")

    result = CliRunner().invoke(cli.app, ["taxonomy", "rebuild", "--preserve-as", "previous"])

    assert result.exit_code == 1
    assert "=== make_seed" in result.stdout
    assert "=== airmux gateway schema" in result.stdout
    assert "=== extract_schemas" not in result.stdout
    assert "FileNotFoundError" in result.stderr
    assert (ready_catalog / "README.md").read_text() == "catalog documentation\n"
    assert (ready_catalog.parent / "previous" / "models").exists()
