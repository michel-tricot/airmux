from __future__ import annotations

import re

from model_audit.provider_docs.base import ModelDocumentation, markdown_price, token_count


def parse_anthropic_model(markdown: str, source: str) -> ModelDocumentation:
    model_match = re.search(r"^Model ID:\s*`([^`]+)`", markdown, flags=re.MULTILINE)
    if model_match is None:
        message = f"Anthropic model page has no model id: {source}"
        raise ValueError(message)
    context = re.search(r"Context window:\s*([\d,.]+\s*[KMB]?)\s*tokens", markdown, flags=re.IGNORECASE)
    output = re.search(r"Max output:\s*([\d,.]+\s*[KMB]?)\s*tokens", markdown, flags=re.IGNORECASE)
    prices = {
        "input_per_mtok": markdown_price(markdown, "Input"),
        "output_per_mtok": markdown_price(markdown, "Output"),
        "cached_input_per_mtok": markdown_price(markdown, "Cache read"),
        "cache_write_per_mtok": markdown_price(markdown, "5m cache write"),
    }
    pricing: dict[str, object] = {name: value for name, value in prices.items() if value is not None}
    one_hour = markdown_price(markdown, "1h cache write")
    if one_hour is not None:
        pricing["tiers"] = {"one_hour_cache_write": {"cache_write_per_mtok": one_hour}}
    values: dict[str, object] = {
        "context_length": token_count(context.group(1)) if context else None,
        "max_output_tokens": token_count(output.group(1)) if output else None,
        "pricing": pricing or None,
    }
    return ModelDocumentation(ids=(model_match.group(1),), source=source, values={name: value for name, value in values.items() if value is not None})
