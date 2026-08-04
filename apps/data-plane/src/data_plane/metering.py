from __future__ import annotations

import functools
from typing import TYPE_CHECKING

import tiktoken

if TYPE_CHECKING:
    from contract import ModelEntry
    from data_plane.canonical import Usage


CACHE_READ_MULT = 0.1  # ephemeral cache hit
CACHE_WRITE_MULT = 1.25  # ephemeral cache write


def cost_breakdown(usage: Usage, model: ModelEntry) -> tuple[float, float]:
    fresh = usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens
    billable_in = fresh + usage.cache_write_tokens * CACHE_WRITE_MULT + usage.cache_read_tokens * CACHE_READ_MULT
    return billable_in * model.input_price_per_mtok / 1_000_000, usage.output_tokens * model.output_price_per_mtok / 1_000_000


@functools.lru_cache(maxsize=64)
def _encoding(upstream_model: str) -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(upstream_model)
    except KeyError:
        return tiktoken.get_encoding("o200k_base")


def estimate_tokens(text: str, model: ModelEntry) -> int:
    """Provider counts win where given; this fills the gap, notably partial accounting after a cancel."""
    if not text:
        return 0
    return len(_encoding(model.upstream_model).encode(text))
