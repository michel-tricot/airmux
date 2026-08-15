"""Anthropic.

/v1/models needs the x-api-key header and an anthropic-version header; a bearer token is
parsed but is for OAuth tokens, not API keys.

The listing carries max_input_tokens and max_tokens, so limits never need borrowing here.
It also carries a nested capabilities tree, which is the only place Anthropic publishes
tool and structured-output support in machine-readable form. Read it rather than assuming:
capability differs across the family.

Pricing is not on the API. The table below is transcribed from the pricing page and
carries a date, because a hand-copied price is a fact with a shelf life.
"""

from .base import ModelSource

# Hand-transcribed from platform.claude.com/docs/en/about-claude/pricing, 2026-08-14.
# USD per million tokens. Anthropic publishes no pricing on the API, so unlike Groq or
# Together this table will rot: re-read the page when a model ships. Cache write is the
# 5-minute rate, which Anthropic documents as 1.25x base input. The 1-hour rate is 2x and
# the read is 0.1x, both derivable from base, so only the write is carried.
PRICING = {
    "claude-fable-5":    (10.0, 50.0, 1.0),
    "claude-opus-5":     (5.0, 25.0, 0.5),
    "claude-opus-4-8":   (5.0, 25.0, 0.5),
    "claude-opus-4-7":   (5.0, 25.0, 0.5),
    "claude-opus-4-6":   (5.0, 25.0, 0.5),
    "claude-opus-4-5":   (5.0, 25.0, 0.5),
    "claude-sonnet-5":   (2.0, 10.0, 0.2),
    "claude-sonnet-4-6": (3.0, 15.0, 0.3),
    "claude-sonnet-4-5": (3.0, 15.0, 0.3),
    "claude-haiku-4-5":  (1.0, 5.0, 0.1),
}


def priced(model_id: str) -> dict | None:
    """Match the id, then the id with its date suffix stripped: claude-opus-4-5-20251101."""
    for key in (model_id, "-".join(model_id.split("-")[:-1])):
        if key in PRICING:
            inp, out, cached = PRICING[key]
            return {
                "input_per_mtok": inp,
                "output_per_mtok": out,
                "cached_input_per_mtok": cached,
                "cache_write_per_mtok": round(inp * 1.25, 4),
            }
    return None



class Anthropic(ModelSource):
    id = "anthropic"
    url = "https://api.anthropic.com/v1/models"
    auth = "header:x-api-key"

    def headers(self, key):
        head = super().headers(key)
        head["anthropic-version"] = "2023-06-01"
        return head

    def normalize(self, item):
        caps = item.get("capabilities") or {}
        supported = lambda name: bool((caps.get(name) or {}).get("supported"))
        inputs = ["text"]
        if supported("image_input"):
            inputs.append("image")
        if supported("pdf_input"):
            inputs.append("pdf")
        return self.record(
            item["id"],
            context_length=item.get("max_input_tokens"),
            max_output_tokens=item.get("max_tokens"),
            input_modalities=inputs,
            output_modalities=["text"],
            supports_tools=supported("code_execution") or bool(caps),
            supports_structured_output=supported("structured_outputs"),
            pricing=priced(item["id"]),
            display_name=item.get("display_name"),
            supports_thinking=supported("thinking"),
            supports_batch=supported("batch"),
        )
