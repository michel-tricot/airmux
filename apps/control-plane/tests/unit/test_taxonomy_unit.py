from __future__ import annotations

from pathlib import Path
from typing import get_type_hints

import pytest
import yaml

import control_plane
from control_plane.fixtures import ROUTED_MODELS
from control_plane.models.common.wire import RequestModel
from control_plane.routes import taxonomy as taxonomy_routes
from control_plane.taxonomy import TaxonomySpec

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


def test_taxonomy_endpoints_use_request_models():
    for endpoint in (taxonomy_routes.create_provider, taxonomy_routes.create_model, taxonomy_routes.apply_instance_taxonomy):
        request_model = get_type_hints(endpoint)["body"]
        assert issubclass(request_model, RequestModel)
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            request_model.model_validate({"unexpected": True})


def test_taxonomy_nested_entries_are_request_models():
    taxonomy = TaxonomySpec.model_validate(
        {
            "providers": [{"provider_id": "stub", "base_url": "https://example.com"}],
            "models": [{"model_id": "echo", "provider_id": "stub", "input_modalities": ["text"], "output_modalities": ["text"]}],
        }
    )
    assert isinstance(taxonomy.providers[0], RequestModel)
    assert isinstance(taxonomy.models[0], RequestModel)
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        TaxonomySpec.model_validate({"providers": [{"provider_id": "stub", "base_url": "https://example.com", "unexpected": True}]})
