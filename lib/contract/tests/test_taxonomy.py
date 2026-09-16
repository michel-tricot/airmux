from __future__ import annotations

from decimal import Decimal

import pytest
import yaml
from pydantic import ValidationError

from contract.taxonomy import dump_taxonomy, load_taxonomy

MODEL = """
models:
- model_id: model
  provider_id: provider
  input_price_per_mtok: 0.014
  output_price_per_mtok: 1.2500
  cache_read_price_per_mtok: 0
  cache_write_price_per_mtok: 0
  input_modalities: [text]
  output_modalities: [text]
"""


def test_taxonomy_loads_money_from_lexical_yaml_and_dumps_plain_scalars() -> None:
    taxonomy = load_taxonomy(MODEL)

    assert taxonomy.models[0].input_price_per_mtok == Decimal("0.014")
    rendered = dump_taxonomy(taxonomy.model_dump())
    assert "input_price_per_mtok: 0.014" in rendered
    assert "output_price_per_mtok: 1.2500" in rendered
    assert "cache_read_price_per_mtok: 0" in rendered
    assert yaml.safe_load("unrelated: 0.1")["unrelated"] == 0.1


@pytest.mark.parametrize("price", ["1e-6", ".inf", ".nan", "0.0000001", "10000000000"])
def test_taxonomy_rejects_invalid_rates(price: str) -> None:
    with pytest.raises((ValidationError, yaml.YAMLError)):
        load_taxonomy(MODEL.replace("0.014", price))
