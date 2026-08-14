from __future__ import annotations

from conftest import MODEL

from data_plane.canonical import Usage
from data_plane.metering import cost_breakdown


def _model():
    return MODEL.model_copy(
        update={
            "input_price_per_mtok": 2.0,
            "output_price_per_mtok": 5.0,
            "cache_read_price_per_mtok": 0.25,
            "cache_write_price_per_mtok": 2.5,
        },
    )


def test_each_usage_bucket_has_a_direct_model_price():
    usage = Usage(input_tokens=1000, output_tokens=40, cache_read_tokens=300, cache_write_tokens=200)
    cost_in, cost_out = cost_breakdown(usage, _model())
    assert cost_in == (500 * 2.0 + 300 * 0.25 + 200 * 2.5) / 1_000_000
    assert cost_out == 40 * 5.0 / 1_000_000


def test_cache_counts_cannot_make_fresh_input_negative():
    usage = Usage(input_tokens=100, cache_read_tokens=80, cache_write_tokens=40)
    cost_in, _ = cost_breakdown(usage, _model())
    assert cost_in == (80 * 0.25 + 40 * 2.5) / 1_000_000
