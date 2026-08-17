"""The model the quickstart curl example names.

The example is the first request a new operator sends, so it must name a model the catalog
serves, spelled the way the gateway resolves it, from a provider a credential was just seeded
for. gpt-4o unprefixed was none of those.
"""

from __future__ import annotations

from cli.auth import example_model

CHEAP_OPENAI = {"model_id": "openai/gpt-5-nano", "provider_id": "openai", "input_price_per_mtok": 0.05}
FLAGSHIP_OPENAI = {"model_id": "openai/gpt-5.2", "provider_id": "openai", "input_price_per_mtok": 1.75}
CHEAP_ANTHROPIC = {"model_id": "anthropic/claude-haiku-4-5", "provider_id": "anthropic", "input_price_per_mtok": 1.0}


def test_picks_the_cheapest_model_of_a_seeded_provider():
    assert example_model([FLAGSHIP_OPENAI, CHEAP_ANTHROPIC, CHEAP_OPENAI], {"openai"}) == "openai/gpt-5-nano"


def test_skips_providers_without_a_credential():
    assert example_model([CHEAP_OPENAI, CHEAP_ANTHROPIC], {"anthropic"}) == "anthropic/claude-haiku-4-5"


def test_falls_back_to_the_whole_catalog_when_nothing_was_seeded():
    assert example_model([FLAGSHIP_OPENAI, CHEAP_ANTHROPIC], set()) == "anthropic/claude-haiku-4-5"


def test_an_empty_catalog_still_yields_a_plausible_spelling():
    assert "/" in example_model([], set())
