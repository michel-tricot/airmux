from __future__ import annotations

import re

from model_audit.provider_docs.base import ModelDocumentation, documented_flag, documented_price, html_cells, token_count

CHAT_FIELD_COUNT = 10
VISION_FIELD_COUNT = 6


def _values(cells: list[str], *, vision: bool) -> dict[str, object]:
    prices = {
        "input_per_mtok": documented_price(cells[4]),
        **({"cached_input_per_mtok": documented_price(cells[5])} if not vision else {}),
        "output_per_mtok": documented_price(cells[5] if vision else cells[6]),
    }
    values: dict[str, object] = {
        "context_length": token_count(cells[3]),
        "input_modalities": ["text", "image"] if vision else ["text"],
        "output_modalities": ["text"],
        "pricing": {name: price for name, price in prices.items() if price is not None},
    }
    if not vision:
        values.update(
            {
                "supports_tools": documented_flag(cells[8]),
                "supports_structured_output": documented_flag(cells[9]),
            }
        )
    return {name: value for name, value in values.items() if value is not None}


def parse_together_models(document: str, source: str) -> tuple[ModelDocumentation, ...]:
    metadata: dict[str, dict[str, object]] = {}
    html_rows = (html_cells(row) for row in re.findall(r"<tr[^>]*>(.*?)</tr>", document, flags=re.DOTALL | re.IGNORECASE))
    rows = [(cells, False) for cells in html_rows if len(cells) == CHAT_FIELD_COUNT]
    section = ""
    for line in document.splitlines():
        if line.startswith("## "):
            section = line.removeprefix("## ").strip().casefold()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        vision = section == "vision models"
        if (vision and len(cells) == VISION_FIELD_COUNT) or (section == "chat models" and len(cells) == CHAT_FIELD_COUNT):
            rows.append((cells, vision))
    for cells, vision in rows:
        if "/" not in cells[2]:
            continue
        model_id = cells[2]
        values = _values(cells, vision=vision)
        current = metadata.setdefault(model_id, {})
        current_pricing = current.get("pricing")
        values_pricing = values.get("pricing")
        current.update({name: value for name, value in values.items() if name != "pricing"})
        if isinstance(current_pricing, dict) and isinstance(values_pricing, dict):
            current["pricing"] = {**current_pricing, **values_pricing}
        elif values_pricing is not None:
            current["pricing"] = values_pricing
    return tuple(ModelDocumentation(ids=(model_id,), source=source, values=values) for model_id, values in metadata.items())
