from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data_plane.canonical import Usage
    from gw_contract import ModelEntry


def cost_usd(usage: Usage, model: ModelEntry) -> float:
    return (usage.input_tokens * model.input_price_per_mtok + usage.output_tokens * model.output_price_per_mtok) / 1_000_000


def estimate_tokens(text: str, model: ModelEntry) -> int:
    raise NotImplementedError
