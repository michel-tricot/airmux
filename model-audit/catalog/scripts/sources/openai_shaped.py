"""Providers whose listing is plain OpenAI-shaped with useful extras.

These share a payload shape but not a vocabulary, so each still maps its own fields. They
are grouped in one module because the differences are small enough that separate files
would be ceremony rather than clarity. Split any of them out the moment it grows a quirk.

All five are readable without a credential, which is why the catalog has them today.
"""

from __future__ import annotations

from .base import ModelSource


class Novita(ModelSource):
    """Richest of the open catalogs: features, modalities, context and per-token pricing.

    Prices are quoted in hundredths of a cent per million tokens, so divide by 10,000.
    Do not treat the number as dollars; it is off by four orders of magnitude.
    """

    id = "novita"
    url = "https://api.novita.ai/openai/v1/models"
    open_access = True

    def normalize(self, item):
        features = item.get("features") or []

        def scale(value):
            return round(value / 10000, 4) if isinstance(value, (int, float)) else None

        return self.record(
            item["id"],
            context_length=item.get("context_size"),
            max_output_tokens=item.get("max_output_tokens"),
            input_modalities=item.get("input_modalities"),
            output_modalities=item.get("output_modalities"),
            supports_tools="function-calling" in features or "tool-calling" in features,
            supports_structured_output="structured-outputs" in features or "json-mode" in features,
            pricing={"input_per_mtok": scale(item.get("input_token_price_per_m")), "output_per_mtok": scale(item.get("output_token_price_per_m"))}
            if item.get("input_token_price_per_m") is not None
            else None,
            display_name=item.get("title") or item.get("display_name"),
        )


class DeepInfra(ModelSource):
    """Limits, pricing and capability tags hide inside a `metadata` object, not at top level.

    tags is the capability signal: chat, vision, vlm, reasoning, prompt_cache, embed,
    image-gen, tts, stt. Non-text kinds are dropped later by model_kind, but the tags are
    the only reason vision is knowable here.
    """

    id = "deepinfra"
    url = "https://api.deepinfra.com/v1/openai/models"
    open_access = True

    def normalize(self, item):
        meta = item.get("metadata") or {}
        tags = meta.get("tags") or []
        pricing = meta.get("pricing") or {}
        return self.record(
            item["id"],
            context_length=meta.get("context_length"),
            max_output_tokens=meta.get("max_tokens"),
            input_modalities=["text"] + (["image"] if {"vision", "vlm"} & set(tags) else []) if tags else None,
            output_modalities=["text"] if tags else None,
            pricing=self.price(pricing.get("input_tokens"), pricing.get("output_tokens"), cached_input_per_mtok=pricing.get("cache_read_tokens"))
            if pricing
            else None,
            tags=tags,
        )


class SambaNova(ModelSource):
    """Small curated catalog. Pricing is a per-token decimal string, like Groq's."""

    id = "sambanova"
    url = "https://api.sambanova.ai/v1/models"
    open_access = True

    def normalize(self, item):
        pricing = item.get("pricing") or {}
        return self.record(
            item["id"],
            context_length=item.get("context_length"),
            max_output_tokens=item.get("max_completion_tokens"),
            pricing=self.price(pricing.get("prompt"), pricing.get("completion")) if pricing else None,
        )


class HuggingFace(ModelSource):
    """A router: each model carries a list of upstream providers, not one set of facts.

    Take the widest context across live routes and the cheapest live route's price, because
    that is what the router will actually pick. status must be checked: dead routes stay in
    the payload, and counting them makes the catalog look larger than it is.
    """

    id = "huggingface"
    url = "https://router.huggingface.co/v1/models"
    open_access = True

    def normalize(self, item):
        arch = item.get("architecture") or {}
        routes = [r for r in (item.get("providers") or []) if r.get("status") == "live"]
        if not routes:
            return None
        cheapest = min(routes, key=lambda r: (r.get("pricing") or {}).get("input") or float("inf"))
        cost = cheapest.get("pricing") or {}
        return self.record(
            item["id"],
            context_length=max((r.get("context_length") or 0) for r in routes) or None,
            input_modalities=arch.get("input_modalities"),
            output_modalities=arch.get("output_modalities"),
            supports_tools=any(r.get("supports_tools") for r in routes),
            supports_structured_output=any(r.get("supports_structured_output") for r in routes),
            pricing={"input_per_mtok": cost.get("input"), "output_per_mtok": cost.get("output")} if cost.get("input") is not None else None,
            routes=sorted({r["provider"] for r in routes if r.get("provider")}),
        )


class Nvidia(ModelSource):
    """Bare ids and nothing else. A key does not change that; verified, do not retry.

    Tested with a real nvapi- key: the authenticated response is byte-identical in shape to
    the anonymous one. Same 102 models, same four fields, zero extras. Per-model endpoints
    like /v1/models/meta/llama-3.3-70b-instruct return the same four fields again.

    The model cards on build.nvidia.com do show context windows and capability tags, but
    they are rendered client side and the /api/ paths under that host return the SPA shell
    with HTTP 200. There is no metadata endpoint behind them to call.

    So an NVIDIA key buys inference access, not catalog data. Limits come from
    enrich_limits, capabilities stay null, and the honest position is that NVIDIA publishes
    no machine-readable catalog beyond model ids.
    """

    id = "nvidia"
    url = "https://integrate.api.nvidia.com/v1/models"
    open_access = True

    def normalize(self, item):
        return self.record(item["id"], owned_by=item.get("owned_by"))
