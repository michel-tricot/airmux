from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import yaml

from model_audit.catalog_ops import ModelDefinition, add_model

if TYPE_CHECKING:
    from pathlib import Path


def root_with_provider(tmp_path: Path) -> Path:
    taxonomy = tmp_path / "taxonomy"
    taxonomy.mkdir()
    (taxonomy / "providers.yml").write_text(yaml.safe_dump({"providers": [{"id": "stub"}]}), encoding="utf-8")
    return tmp_path


def test_adding_one_model_keeps_its_authoritative_source(tmp_path):
    root = root_with_provider(tmp_path)

    path = add_model(
        root,
        "stub",
        ModelDefinition(
            id="new-model",
            source="https://provider.example/docs/models/new-model",
            context_window=8192,
            max_output_tokens=1024,
        ),
    )

    model = json.loads(path.read_text(encoding="utf-8"))["models"][0]
    assert model["source"] == "https://provider.example/docs/models/new-model"
    assert model["context_length"] == 8192


def test_adding_a_model_requires_a_known_provider(tmp_path):
    root = root_with_provider(tmp_path)

    with pytest.raises(ValueError, match=r"provider unknown is not in providers\.yml"):
        add_model(root, "unknown", ModelDefinition(id="model", source="https://provider.example/models/model"))


def test_replacing_a_model_is_explicit_and_preserves_existing_metadata(tmp_path):
    root = root_with_provider(tmp_path)
    definition = ModelDefinition(
        id="new-model",
        source="https://provider.example/docs/models/new-model",
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
