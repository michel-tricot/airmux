"""The model the quickstart curl example names.

The example is the first request a new operator sends, so it must name a model the catalog
serves, spelled the way the gateway resolves it, from a provider a credential was just seeded
for. The catalog here is the taxonomy endpoint's wire shape: models name their provider by id,
and the provider entries carry the names credentials are seeded under.
"""

from __future__ import annotations

from cli.auth import example_model

PROVIDERS = [
    {"id": "9b7e1c2a-0000-7000-8000-000000000001", "name": "openai"},
    {"id": "9b7e1c2a-0000-7000-8000-000000000002", "name": "anthropic"},
]
CHEAP_OPENAI = {"name": "openai/gpt-5-nano", "provider_id": PROVIDERS[0]["id"], "input_price_per_mtok": 0.05}
FLAGSHIP_OPENAI = {"name": "openai/gpt-5.2", "provider_id": PROVIDERS[0]["id"], "input_price_per_mtok": 1.75}
CHEAP_ANTHROPIC = {"name": "anthropic/claude-haiku-4-5", "provider_id": PROVIDERS[1]["id"], "input_price_per_mtok": 1.0}


def catalog(*models: dict) -> dict:
    return {"providers": PROVIDERS, "models": list(models)}


def test_picks_the_cheapest_model_of_a_seeded_provider():
    assert example_model(catalog(FLAGSHIP_OPENAI, CHEAP_ANTHROPIC, CHEAP_OPENAI), {"openai"}) == "openai/gpt-5-nano"


def test_skips_providers_without_a_credential():
    assert example_model(catalog(CHEAP_OPENAI, CHEAP_ANTHROPIC), {"anthropic"}) == "anthropic/claude-haiku-4-5"


def test_falls_back_to_the_whole_catalog_when_nothing_was_seeded():
    assert example_model(catalog(FLAGSHIP_OPENAI, CHEAP_ANTHROPIC), set()) == "anthropic/claude-haiku-4-5"


def test_an_empty_catalog_still_yields_a_plausible_spelling():
    assert "/" in example_model({}, set())
