"""OpenAI.

/v1/models is deliberately bare: id, created, owned_by and shutdown_date. No context
window, no output limit, no pricing, no capabilities. Limits come from enrich_limits and
pricing from the transcribed table below, which carries a date because it will rot.

Do not try to infer limits from the model id. The names encode marketing tiers, not
context windows, and the mapping has broken at every generation.

shutdown_date is worth carrying: it is the only machine-readable deprecation signal any
provider in the catalog publishes.
"""

import re

from .base import ModelSource

# Hand-transcribed from developers.openai.com/api/docs/pricing, 2026-08-14.
# USD per million tokens, as (input, output, cached input). OpenAI publishes no pricing on
# the API, so this table will rot: re-read the page when a model ships.
#
# Only models the page actually lists are here. Legacy ids the catalog still returns, such
# as gpt-3.5-turbo, davinci-002 and gpt-4, are absent from the pricing page and stay unpriced
# rather than being guessed at.
PRICING = {
    "gpt-5.6-sol": (5.0, 30.0, 0.5),   "gpt-5.6-terra": (2.0, 12.0, 0.2),
    "gpt-5.6-luna": (0.2, 1.2, 0.02),  "gpt-5.5": (5.0, 30.0, 0.5),
    "gpt-5.5-pro": (30.0, 180.0, None), "gpt-5.4": (2.5, 15.0, 0.25),
    "gpt-5.4-mini": (0.75, 4.5, 0.075), "gpt-5.4-nano": (0.2, 1.25, 0.02),
    "gpt-5.4-pro": (30.0, 180.0, None), "gpt-5.2": (1.75, 14.0, 0.175),
    "gpt-5.2-pro": (21.0, 168.0, None), "gpt-5.1": (1.25, 10.0, 0.125),
    "gpt-5": (1.25, 10.0, 0.125),      "gpt-5-mini": (0.25, 2.0, 0.025),
    "gpt-5-nano": (0.05, 0.4, 0.005),  "gpt-5-pro": (15.0, 120.0, None),
    "gpt-4.1": (2.0, 8.0, 0.5),        "gpt-4.1-mini": (0.4, 1.6, 0.1),
    "gpt-4.1-nano": (0.1, 0.4, 0.025), "gpt-4o": (2.5, 10.0, 1.25),
    "gpt-4o-2024-05-13": (5.0, 15.0, None), "gpt-4o-mini": (0.15, 0.6, 0.075),
    "o1": (15.0, 60.0, 7.5),           "o1-pro": (150.0, 600.0, None),
    "o3": (2.0, 8.0, 0.5),             "o3-pro": (20.0, 80.0, None),
    "o3-mini": (1.1, 4.4, 0.55),       "o4-mini": (1.1, 4.4, 0.275),
}

_DATED = re.compile(r"-\d{4}-\d{2}-\d{2}$")


def priced(model_id: str) -> dict | None:
    """Exact id first, then with a trailing date stripped: gpt-5-2025-08-07 prices as gpt-5."""
    for key in (model_id, _DATED.sub("", model_id)):
        if key in PRICING:
            inp, out, cached = PRICING[key]
            out_price = {"input_per_mtok": inp, "output_per_mtok": out}
            if cached is not None:
                out_price["cached_input_per_mtok"] = cached
            return out_price
    return None



class OpenAI(ModelSource):
    id = "openai"
    url = "https://api.openai.com/v1/models"

    def normalize(self, item):
        return self.record(item["id"], pricing=priced(item["id"]),
                           shutdown_date=item.get("shutdown_date"))
