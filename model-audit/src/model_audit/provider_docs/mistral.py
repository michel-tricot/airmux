from __future__ import annotations

import html
import re
import urllib.parse

from model_audit.provider_docs.base import ModelDocumentation, token_count

PAIR_FIELD_COUNT = 2


def parse_mistral_index(document: str, source: str) -> tuple[str, ...]:
    paths = re.findall(r'href="(/models/[^"?#]+)"', document, flags=re.IGNORECASE)
    return tuple(dict.fromkeys(urllib.parse.urljoin(source, path) for path in paths))


def parse_mistral_model(document: str, source: str) -> ModelDocumentation:
    ids = tuple(dict.fromkeys(re.findall(r'title="Click to copy: ([^"]+)"', document)))
    if not ids:
        message = f"Mistral model page has no API model id: {source}"
        raise ValueError(message)
    context = re.search(r">Context</span>.*?<div[^>]*text-lg[^>]*>([\d,.]+\s*[KMB]?)</div>", document, flags=re.DOTALL | re.IGNORECASE)
    serialized = html.unescape(document).replace(r"\"", '"')
    pricing_match = re.search(r'"pricing":\{"type":"custom".*?"input":\[(.*?)\],\s*"output":\[(.*?)\]\}', serialized, flags=re.DOTALL)
    pricing: dict[str, float] = {}
    if pricing_match is not None:
        input_prices = [
            float(price.group(1))
            for item in re.findall(r"\{[^{}]*\}", pricing_match.group(1))
            if '"denominator":"/M Tokens"' in item and (price := re.search(r'"price":([\d.]+)', item)) is not None
        ]
        output_prices = [
            float(price.group(1))
            for item in re.findall(r"\{[^{}]*\}", pricing_match.group(2))
            if '"denominator":"/M Tokens"' in item and (price := re.search(r'"price":([\d.]+)', item)) is not None
        ]
        if input_prices:
            pricing["input_per_mtok"] = input_prices[0]
        if len(input_prices) > 1:
            pricing["cached_input_per_mtok"] = input_prices[1]
        if output_prices:
            pricing["output_per_mtok"] = output_prices[0]
    elif ">Price</span>" in document:
        pricing_section = document.split(">Price</span>", 1)[1]
        prices = [float(value) for value in re.findall(r"\$(?:<!--\s*-->)?([\d.]+)", pricing_section)[:PAIR_FIELD_COUNT]]
        if len(prices) == PAIR_FIELD_COUNT:
            pricing = {"input_per_mtok": prices[0], "output_per_mtok": prices[1]}
    values: dict[str, object] = {"context_length": token_count(context.group(1)) if context else None}
    if pricing:
        values["pricing"] = pricing
    return ModelDocumentation(ids=ids, source=source, values={name: value for name, value in values.items() if value is not None})
