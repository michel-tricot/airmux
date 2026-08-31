from __future__ import annotations

import re

from model_audit.provider_docs.base import ModelDocumentation, documented_flag, documented_price, html_cells, token_count

TOGETHER_FIELD_COUNT = 10


def parse_together_models(document: str, source: str) -> tuple[ModelDocumentation, ...]:
    metadata = []
    html_rows = (html_cells(row) for row in re.findall(r"<tr[^>]*>(.*?)</tr>", document, flags=re.DOTALL | re.IGNORECASE))
    markdown_rows = ([cell.strip() for cell in line.strip().strip("|").split("|")] for line in document.splitlines() if line.startswith("|"))
    for cells in (*html_rows, *markdown_rows):
        if len(cells) != TOGETHER_FIELD_COUNT or "/" not in cells[2]:
            continue
        prices = {
            "input_per_mtok": documented_price(cells[4]),
            "cached_input_per_mtok": documented_price(cells[5]),
            "output_per_mtok": documented_price(cells[6]),
        }
        values: dict[str, object] = {
            "context_length": token_count(cells[3]),
            "supports_tools": documented_flag(cells[8]),
            "supports_structured_output": documented_flag(cells[9]),
            "pricing": {name: price for name, price in prices.items() if price is not None},
        }
        metadata.append(
            ModelDocumentation(ids=(cells[2],), source=source, values={name: value for name, value in values.items() if value is not None})
        )
    return tuple(metadata)
