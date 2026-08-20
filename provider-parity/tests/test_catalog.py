from __future__ import annotations

from pathlib import Path

from provider_parity.catalog import load_catalog

ROOT = Path(__file__).parents[2]


def test_catalog_expands_routable_models_across_proven_surfaces():
    catalog = load_catalog(ROOT / "taxonomy")

    assert catalog.targets
    assert {target.egress_kind for target in catalog.targets} == {"anthropic", "openai_compatible", "openai_responses"}
    assert all(target.model_id.startswith(f"{target.provider_id}/") for target in catalog.targets)
    assert all(target.upstream_model for target in catalog.targets)
    assert all(target.credential_env.endswith("_API_KEY") for target in catalog.targets)


def test_surface_specific_evidence_stays_on_the_target():
    catalog = load_catalog(ROOT / "taxonomy")
    responses = [target for target in catalog.targets if target.provider_id == "openai" and target.endpoint == "responses"]
    chat = [target for target in catalog.targets if target.provider_id == "openai" and target.endpoint == "chat/completions"]

    assert responses
    assert chat
    assert all(target.surface_id == "oai_responses" for target in responses)
    assert all(target.surface_id == "oai" for target in chat)
