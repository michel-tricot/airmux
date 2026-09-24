from __future__ import annotations

import json
from decimal import Decimal

import pytest

from model_audit.catalog_tasks.canonical import dumps, validate_prices


def test_catalog_json_preserves_decimal_lexemes() -> None:
    rendered = dumps({"pricing": {"input_per_mtok": Decimal("0.123456789012345678")}})

    assert '"input_per_mtok": 0.123456789012345678' in rendered
    assert json.loads(rendered, parse_float=Decimal)["pricing"]["input_per_mtok"] == Decimal("0.123456789012345678")


def test_catalog_rejects_float_prices() -> None:
    with pytest.raises(TypeError, match="exact decimals"):
        validate_prices({"pricing": {"input_per_mtok": 0.1}})
