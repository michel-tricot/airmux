from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest
import yaml

from model_audit.catalog_ops import (
    ModelDefinition,
    ProviderDefinition,
    SchemaDefinition,
    add_model,
    add_provider,
    load_provider_entries,
    preflight_source,
    provider_sources,
    retain_documented_models,
)


def root_with_provider(tmp_path: Path) -> Path:
    taxonomy = tmp_path / "taxonomy"
    taxonomy.mkdir()
    (taxonomy / "providers.yml").write_text(yaml.safe_dump({"providers": [{"id": "stub"}]}), encoding="utf-8")
    return tmp_path


def provider_definition() -> ProviderDefinition:
    return ProviderDefinition(
        id="stub",
        name="Stub AI",
        homepage="https://provider.example",
        docs="https://provider.example/docs",
        base_url="https://api.provider.example/v1",
        models_url="https://api.provider.example/v1/models",
        ingress=("oai",),
        primary_surface="oai",
        auth=("bearer",),
        env_var="STUB_API_KEY",
    )


class OfflineSource:
    provider_id = "offline"
    url = "https://offline.example/models"
    open_access = False
    definition: ProviderDefinition | None = None
    schemas: tuple[SchemaDefinition, ...] = ()

    def __init__(self) -> None:
        self.documented_schemas: dict[str, dict[str, object]] = {}

    def fetch(self, key: str | None) -> object:
        message = "offline"
        raise OSError(message)

    def items(self, payload: object) -> list[dict[str, object]]:
        return []

    def normalize(self, item: dict[str, object]) -> dict[str, object] | None:
        return item

    def enrich(self, models: list[dict[str, object]]) -> list[dict[str, object]]:
        return models


class IncompleteSource(OfflineSource):
    provider_id = "incomplete"

    def fetch(self, key: str | None) -> object:
        return [{"id": "model"}]

    def items(self, payload: object) -> list[dict[str, object]]:
        return cast("list[dict[str, object]]", payload) if isinstance(payload, list) else []

    def normalize(self, item: dict[str, object]) -> dict[str, object] | None:
        return {"id": item["id"], "input_modalities": None, "output_modalities": []}


def test_provider_preflight_reports_acquisition_failures():
    with pytest.raises(RuntimeError, match="model acquisition failed: offline"):
        preflight_source(OfflineSource(), None)


def test_provider_preflight_names_models_with_incomplete_modalities():
    with pytest.raises(
        RuntimeError,
        match=r"incomplete/model\.input_modalities, incomplete/model\.output_modalities",
    ):
        preflight_source(IncompleteSource(), None)


def test_provider_sync_retains_documented_models_missing_from_the_api():
    acquired: list[dict[str, object]] = [{"id": "api-model", "input_modalities": ["text"], "output_modalities": ["text"]}]
    previous: list[dict[str, object]] = [
        {"id": "api-model", "source": "https://provider.example/api-model", "supports_tools": True},
        {"id": "docs-model", "source": "https://provider.example/docs-model", "input_modalities": ["text"], "output_modalities": ["text"]},
        {"id": "retired-api-model", "input_modalities": ["text"], "output_modalities": ["text"]},
    ]

    retained = retain_documented_models(acquired, previous)

    assert retained == [acquired[0], previous[1]]


def test_adding_a_provider_uses_a_typed_definition_and_removes_its_candidate(tmp_path):
    taxonomy = tmp_path / "taxonomy"
    taxonomy.mkdir()
    (taxonomy / "providers.yml").write_text(yaml.safe_dump({"providers": []}), encoding="utf-8")
    (taxonomy / "candidates.yml").write_text(
        yaml.safe_dump({"candidates": [{"id": "stub", "name": "Stub candidate"}, {"id": "other", "name": "Other"}]}),
        encoding="utf-8",
    )

    added = add_provider(tmp_path, provider_definition())

    providers = yaml.safe_load((taxonomy / "providers.yml").read_text(encoding="utf-8"))["providers"]
    candidates = yaml.safe_load((taxonomy / "candidates.yml").read_text(encoding="utf-8"))["candidates"]
    assert added.id == "stub"
    assert providers[0]["models_url"] == "https://api.provider.example/v1/models"
    assert providers[0]["primary_surface"] == "oai"
    assert [candidate["id"] for candidate in candidates] == ["other"]
    assert (taxonomy / "icons" / "stub.svg").exists()


def test_adding_the_first_provider_initializes_an_empty_catalog(tmp_path):
    added = add_provider(tmp_path, provider_definition())

    providers = yaml.safe_load((tmp_path / "taxonomy" / "providers.yml").read_text(encoding="utf-8"))["providers"]
    assert added.id == "stub"
    assert [provider["id"] for provider in providers] == ["stub"]
    assert (tmp_path / "taxonomy" / "icons" / "stub.svg").exists()


def test_provider_entries_do_not_require_a_router_catalog(tmp_path):
    taxonomy = tmp_path / "taxonomy"
    taxonomy.mkdir()
    (taxonomy / "providers.yml").write_text(yaml.safe_dump({"providers": [{"id": "stub"}]}), encoding="utf-8")

    assert load_provider_entries(taxonomy) == {"stub": {"id": "stub"}}


def test_replacing_a_provider_is_explicit(tmp_path):
    taxonomy = tmp_path / "taxonomy"
    taxonomy.mkdir()
    (taxonomy / "providers.yml").write_text(yaml.safe_dump({"providers": []}), encoding="utf-8")
    definition = provider_definition()
    add_provider(tmp_path, definition)
    providers_path = taxonomy / "providers.yml"
    document = yaml.safe_load(providers_path.read_text(encoding="utf-8"))
    document["providers"][0]["schema"] = {"completion": {"oai": {"request": "schema.json"}}}
    providers_path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        add_provider(tmp_path, definition)

    replaced = definition.model_copy(update={"name": "Updated Stub"})
    add_provider(tmp_path, replaced, replace=True)
    providers = yaml.safe_load((taxonomy / "providers.yml").read_text(encoding="utf-8"))["providers"]
    assert providers[0]["name"] == "Updated Stub"
    assert providers[0]["schema"] == {"completion": {"oai": {"request": "schema.json"}}}


def test_every_active_provider_has_an_auto_discovered_typed_source():
    root = Path(__file__).parents[2]
    active = {provider["id"] for provider in yaml.safe_load((root / "taxonomy" / "providers.yml").read_text(encoding="utf-8"))["providers"]}
    sources = provider_sources()

    assert active <= set(sources)
    assert all(sources[provider].definition is not None for provider in active)


def test_readme_provider_source_is_discovered_and_maps_models(tmp_path):
    package_root = Path(__file__).parents[1]
    readme = (package_root / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Provider sources\n", 1)[1].split("\n## ", 1)[0]
    example = section.split("```python\n", 1)[1].split("\n```", 1)[0]
    package = shutil.copytree(package_root / "src" / "model_audit", tmp_path / "model_audit")
    (package / "catalog_tasks" / "sources" / "example.py").write_text(example, encoding="utf-8")
    script = """
from model_audit.catalog_ops import provider_sources

source = provider_sources()["example"]
assert type(source).__module__ == "model_audit.catalog_tasks.sources.example"
assert source.provider_id == source.definition.id == "example"
assert source.url == source.definition.models_url == "https://api.example.ai/v1/models"
assert source.schemas[0].url == source.definition.openapi == "https://api.example.ai/openapi.json"
assert source.schemas[0].surface == source.definition.primary_surface == "oai"
assert source.schemas[0].path_pattern == r"chat/completions$"
items = source.items({"data": [{"id": "example-chat", "context_length": 32768, "max_output_tokens": 4096, "ignored": "extra"}]})
assert len(items) == 1
assert source.normalize(items[0]) == {
    "id": "example-chat",
    "context_length": 32768,
    "max_output_tokens": 4096,
    "input_modalities": None,
    "output_modalities": None,
    "supports_tools": None,
    "supports_structured_output": None,
    "pricing": None,
}
"""
    result = subprocess.run(  # noqa: S603 fixed interpreter executes the repository-owned example in a temporary package
        [sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_every_active_model_has_schema_discovery_evidence():
    root = Path(__file__).parents[2]
    active = {provider["id"] for provider in yaml.safe_load((root / "taxonomy" / "providers.yml").read_text(encoding="utf-8"))["providers"]}

    for path in sorted((root / "taxonomy" / "models").glob("*.json")):
        if path.stem in active:
            models = json.loads(path.read_text(encoding="utf-8"))["models"]
            assert models
            assert all("model_discovery" in model.get("parameter_evidence", {}) for model in models), path.stem


def test_request_field_reports_keep_airmux_first_and_exclude_router_evidence():
    taxonomy = Path(__file__).parents[2] / "taxonomy"

    for ingress in ("oai", "anthropic"):
        report = json.loads((taxonomy / "reports" / f"{ingress}-request-fields.json").read_text(encoding="utf-8"))
        column_ids = [column["id"] for column in report["columns"]]
        assert column_ids[0] == "airmux"
        assert "openrouter" not in column_ids
        assert b"\r" not in (taxonomy / "reports" / f"{ingress}-request-fields.csv").read_bytes()


def test_adding_one_model_keeps_its_authoritative_source(tmp_path):
    root = root_with_provider(tmp_path)

    path = add_model(
        root,
        "stub",
        ModelDefinition(
            id="new-model",
            source="https://provider.example/docs/models/new-model",
            input_modalities=("text", "image"),
            output_modalities=("text",),
            context_window=8192,
            max_output_tokens=1024,
        ),
    )

    model = json.loads(path.read_text(encoding="utf-8"))["models"][0]
    assert model["source"] == "https://provider.example/docs/models/new-model"
    assert model["context_length"] == 8192
    assert model["input_modalities"] == ["text", "image"]
    assert model["output_modalities"] == ["text"]


@pytest.mark.parametrize("field", ["input_modalities", "output_modalities"])
def test_adding_a_model_requires_each_modality_direction(field):
    values = {
        "id": "model",
        "source": "https://provider.example/models/model",
        "input_modalities": ("text",),
        "output_modalities": ("text",),
    }
    values[field] = ()

    with pytest.raises(ValueError, match="at least 1 item"):
        ModelDefinition.model_validate(values)


def test_adding_a_model_requires_a_known_provider(tmp_path):
    root = root_with_provider(tmp_path)

    with pytest.raises(ValueError, match=r"provider unknown is not in providers\.yml"):
        add_model(
            root,
            "unknown",
            ModelDefinition(
                id="model",
                source="https://provider.example/models/model",
                input_modalities=("text",),
                output_modalities=("text",),
            ),
        )


def test_replacing_a_model_is_explicit_and_preserves_existing_metadata(tmp_path):
    root = root_with_provider(tmp_path)
    definition = ModelDefinition(
        id="new-model",
        source="https://provider.example/docs/models/new-model",
        input_modalities=("text",),
        output_modalities=("text",),
        context_window=8192,
        max_output_tokens=1024,
    )
    path = add_model(root, "stub", definition)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["models"][0]["supports_tools"] = True
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        add_model(root, "stub", definition)

    replacement = definition.model_copy(update={"context_window": 16384, "max_output_tokens": 2048})
    add_model(root, "stub", replacement, replace=True)
    model = json.loads(path.read_text(encoding="utf-8"))["models"][0]
    assert model["context_length"] == 16384
    assert model["supports_tools"] is True


def test_together_source_starts_chat_models_at_text_to_text():
    source = provider_sources()["together"]

    model = source.normalize({"id": "org/model", "type": "chat", "pricing": {"input": 1, "output": 2}})

    assert model is not None
    assert model["input_modalities"] == ["text"]
    assert model["output_modalities"] == ["text"]


def test_together_source_adds_documented_vision_input(monkeypatch):
    source = provider_sources()["together"]
    module = sys.modules[type(source).__module__]
    monkeypatch.setattr(
        module,
        "fetch_text",
        lambda _: (
            """
## Chat models
| Org | Model | org/model | 8192 | $1 | - | $2 | FP8 | Yes | Yes |
## Vision models
| Org | Model | org/model | 8192 | $1 | $2 |
"""
        ),
    )
    models: list[dict[str, object]] = [{"id": "org/model", "input_modalities": ["text"], "output_modalities": ["text"]}]

    enriched = source.enrich(models)

    assert enriched[0]["input_modalities"] == ["text", "image"]


@pytest.mark.parametrize("model_id", ["gpt-3.5-turbo-16k", "gpt-5-search-api", "gpt-5-search-api-2025-10-14"])
def test_openai_source_keeps_directly_verified_text_models_complete(model_id):
    source = provider_sources()["openai"]

    model = source.normalize({"id": model_id})

    assert model is not None
    assert model["input_modalities"] == ["text"]
    assert model["output_modalities"] == ["text"]
