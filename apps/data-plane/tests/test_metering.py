from __future__ import annotations

from conftest import MODEL

from contract import ProviderEntry
from data_plane.canonical import Usage
from data_plane.metering import cost_breakdown


def _provider(read_mult: float, write_mult: float = 1.0) -> ProviderEntry:
    return ProviderEntry(
        provider_id="p",
        kind="openai_compatible",
        base_url="https://x/v1",
        cache_read_multiplier=read_mult,
        cache_write_multiplier=write_mult,
    )


def test_cache_read_discounted_by_provider_multiplier():
    usage = Usage(input_tokens=1000, cache_read_tokens=800)  # 200 fresh + 800 cached, input price 1.0 / Mtok
    full, _ = cost_breakdown(usage, MODEL, _provider(1.0))
    half, _ = cost_breakdown(usage, MODEL, _provider(0.5))  # OpenAI-style
    tenth, _ = cost_breakdown(usage, MODEL, _provider(0.1))  # Anthropic-style
    # fresh 200 always billed; cached 800 scaled by the multiplier
    assert full == 1000 / 1_000_000
    assert half == (200 + 800 * 0.5) / 1_000_000
    assert tenth == (200 + 800 * 0.1) / 1_000_000


def test_cache_write_premium():
    usage = Usage(input_tokens=1000, cache_write_tokens=800)
    cost, _ = cost_breakdown(usage, MODEL, _provider(0.1, 1.25))
    assert cost == (200 + 800 * 1.25) / 1_000_000
