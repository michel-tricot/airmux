from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from provider_profile import catalog_headers, endpoints, inference_headers, select_provider_ids


def providers() -> dict[str, dict]:
    taxonomy = SCRIPTS.parents[3] / "taxonomy"
    records = yaml.safe_load((taxonomy / "providers.yml").read_text())["providers"]
    return {provider["id"]: provider for provider in records}


def test_surface_profiles_drive_endpoint_and_auth_selection():
    catalog = providers()

    assert endpoints(catalog["openai"]) == ("chat/completions", "responses")
    assert inference_headers(catalog["anthropic"], "messages", "secret")["x-api-key"] == "secret"
    assert inference_headers(catalog["xai"], "messages", "secret")["x-api-key"] == "secret"
    assert inference_headers(catalog["xai"], "chat/completions", "secret")["Authorization"] == "Bearer secret"


def test_model_catalog_auth_comes_from_provider_data():
    catalog = providers()

    assert catalog_headers(catalog["anthropic"], "secret") == {
        "x-api-key": "secret",
        "anthropic-version": "2023-06-01",
    }
    assert catalog_headers(catalog["cerebras"], None) == {}


def test_unknown_provider_selection_fails():
    with pytest.raises(ValueError, match="unknown providers: typo"):
        select_provider_ids({"typo"}, {"openai"})
