from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from contract.money import UsdAmount, UsdRate


class Money(BaseModel):
    rate: UsdRate
    amount: UsdAmount


def test_money_accepts_exact_strings_and_serializes_fixed_point() -> None:
    money = Money.model_validate_json('{"rate":"0.000001","amount":"0.000000000001"}')

    assert money.rate == Decimal("0.000001")
    assert money.amount == Decimal("0.000000000001")
    assert money.model_dump_json() == '{"rate":"0.000001","amount":"0.000000000001"}'


@pytest.mark.parametrize("value", [0, 0.1, "1e-6", "NaN", "Infinity", "-1", "10000000000", "0.0000001"])
def test_rate_rejects_non_decimal_strings_and_out_of_range_values(value: object) -> None:
    with pytest.raises(ValidationError):
        Money.model_validate({"rate": value, "amount": "0"})


@pytest.mark.parametrize("value", [0, 0.1, "1e-12", "NaN", "Infinity", "-1", "10000000000000000", "0.0000000000001"])
def test_amount_rejects_non_decimal_strings_and_out_of_range_values(value: object) -> None:
    with pytest.raises(ValidationError):
        Money.model_validate({"rate": "0", "amount": value})
