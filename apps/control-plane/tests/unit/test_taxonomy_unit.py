from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import control_plane
from contract.taxonomy import TaxonomySpec
from control_plane.fixtures import ROUTED_MODELS

REPO_ROOT = Path(control_plane.__file__).resolve().parents[4]


def test_empty_taxonomy_parses_to_defaults():
    spec = TaxonomySpec.model_validate(yaml.safe_load("{}"))
    assert spec.providers == []
    assert spec.models == []


def test_fixture_models_exist_in_the_shipped_taxonomy():
    spec = TaxonomySpec.model_validate(yaml.safe_load((REPO_ROOT / "taxonomy" / "taxonomy.yml").read_text(encoding="utf-8")))
    assert set(ROUTED_MODELS) <= {model.model_id for model in spec.models}


@pytest.mark.parametrize(
    "modalities",
    [
        {},
        {"input_modalities": [], "output_modalities": ["text"]},
        {"input_modalities": ["text"], "output_modalities": []},
    ],
)
def test_taxonomy_rejects_missing_or_empty_model_modalities(modalities):
    with pytest.raises(ValueError, match=r"input_modalities|output_modalities"):
        TaxonomySpec.model_validate({"models": [{"model_id": "echo", "provider_id": "stub", **modalities}]})


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
