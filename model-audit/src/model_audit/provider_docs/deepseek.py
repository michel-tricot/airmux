from __future__ import annotations

import re
from decimal import Decimal

from model_audit.provider_docs.base import ModelDocumentation, html_cells, token_count

PRICE_FIELD_COUNT = 3


def _rows(document: str, label: str) -> list[list[Decimal]]:
    rows = re.findall(rf">{label}</td>(.*?)</tr>", document, flags=re.DOTALL | re.IGNORECASE)
    return [[Decimal(amount) for amount in re.findall(r"\$([\d.]+)", row)] for row in rows]


def parse_deepseek_pricing(document: str, source: str) -> dict[str, ModelDocumentation]:
    model_row = re.search(r"<tr><td[^>]*>MODEL</td>(.*?)</tr>", document, flags=re.DOTALL | re.IGNORECASE)
    if model_row is None:
        message = f"DeepSeek pricing page has no model row: {source}"
        raise ValueError(message)
    models = html_cells(model_row.group(1))
    context_match = re.search(r"CONTEXT LENGTH</td><td[^>]*>([^<]+)", document, flags=re.IGNORECASE)
    output_match = re.search(r"MAX OUTPUT</td><td[^>]*>(?:MAXIMUM:\s*)?([^<]+)", document, flags=re.IGNORECASE)
    off_peak = _rows(document, "OFF-PEAK")
    peak = _rows(document, "PEAK")
    if len(off_peak) != PRICE_FIELD_COUNT or len(peak) != PRICE_FIELD_COUNT or any(len(row) != len(models) for row in (*off_peak, *peak)):
        message = f"DeepSeek pricing page has an unrecognized rate matrix: {source}"
        raise ValueError(message)
    metadata = {}
    for index, model_id in enumerate(models):
        peak_price: dict[str, object] = {
            "input_per_mtok": peak[1][index],
            "cached_input_per_mtok": peak[0][index],
            "output_per_mtok": peak[2][index],
        }
        off_peak_price: dict[str, Decimal] = {
            "input_per_mtok": off_peak[1][index],
            "cached_input_per_mtok": off_peak[0][index],
            "output_per_mtok": off_peak[2][index],
        }
        peak_price["tiers"] = {"off_peak": off_peak_price, "peak": dict(peak_price)}
        values: dict[str, object] = {
            "context_length": token_count(context_match.group(1)) if context_match else None,
            "max_output_tokens": token_count(output_match.group(1)) if output_match else None,
            "input_modalities": ["text", "image"] if "vision" in model_id else ["text"],
            "output_modalities": ["text"],
            "supports_tools": True,
            "supports_structured_output": True,
            "supports_thinking": True,
            "pricing": peak_price,
        }
        metadata[model_id] = ModelDocumentation(ids=(model_id,), source=source, values=values)
    return metadata
