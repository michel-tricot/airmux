from __future__ import annotations

import re
import urllib.parse

from model_audit.provider_docs.base import ModelDocumentation

PRICE_FIELD_COUNT = 3


def _price_triplet(value: str) -> dict[str, float] | None:
    amounts = [float(amount) for amount in re.findall(r"\\?\$([\d.]+)", value)]
    if len(amounts) != PRICE_FIELD_COUNT:
        return None
    return {"input_per_mtok": amounts[0], "cached_input_per_mtok": amounts[1], "output_per_mtok": amounts[2]}


def parse_fireworks_pricing(markdown: str, source: str) -> dict[str, ModelDocumentation]:
    pattern = re.compile(
        r"\[[^\]]+\]\(https://app\.fireworks\.ai/models/fireworks/([^)]+)\)\s*\|\s*([^|]+)\|\s*([^|]+)\|",
        flags=re.IGNORECASE,
    )
    prices: dict[str, ModelDocumentation] = {}
    for model_id, standard_value, priority_value in pattern.findall(markdown):
        if model_id in prices or (standard := _price_triplet(standard_value)) is None:
            continue
        priority = _price_triplet(priority_value)
        pricing: dict[str, object] = dict(standard)
        if priority is not None:
            pricing["tiers"] = {"priority": priority}
        prices[model_id] = ModelDocumentation(ids=(model_id,), source=source, values={"pricing": pricing})
    return prices


def parse_fireworks_model(document: str, source: str) -> ModelDocumentation:
    model_id = urllib.parse.urlparse(source).path.rstrip("/").rsplit("/", 1)[-1]
    if not model_id:
        message = f"Fireworks model page has no model id: {source}"
        raise ValueError(message)
    serverless = re.search(r">Serverless</span>.*?<span[^>]*>([^<]+)</span>", document, flags=re.DOTALL | re.IGNORECASE)
    values: dict[str, object] = {}
    if serverless is not None and serverless.group(1).strip().lower() == "not supported":
        values["source_conflicts"] = ["provider API reports supportsServerless=true; official model page reports Serverless: Not supported"]
    return ModelDocumentation(ids=(model_id,), source=source, values=values)
