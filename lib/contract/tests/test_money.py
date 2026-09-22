from __future__ import annotations

from decimal import Decimal, localcontext

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


@pytest.mark.parametrize("precision", [28, 64])
@pytest.mark.parametrize(
    ("rate", "amount"),
    [
        ("9999999999.999999", "9999999999999999.999999999999"),
        ("0.000001", "0.000000000001"),
        ("1.230000", "1.230000000000"),
        ("0", "0"),
    ],
)
def test_decimal_money_preserves_fixed_point_precision(rate: str, amount: str, precision: int) -> None:
    with localcontext() as context:
        context.prec = precision
        money = Money(rate=Decimal(rate), amount=Decimal(amount))
        assert money.rate.as_tuple() == Decimal(rate).as_tuple()
        assert money.amount.as_tuple() == Decimal(amount).as_tuple()
        assert money.model_dump(mode="json") == {"rate": rate, "amount": amount}


@pytest.mark.parametrize(
    ("rate", "amount"),
    [
        ("10000000000", "0"),
        ("0.0000000", "0"),
        ("-0.000001", "0"),
        ("NaN", "0"),
        ("Infinity", "0"),
        ("0", "10000000000000000"),
        ("0", "0.0000000000000"),
        ("0", "-0.000000000001"),
        ("0", "NaN"),
        ("0", "Infinity"),
    ],
)
def test_decimal_money_rejects_invalid_precision_and_nonfinite_values(rate: str, amount: str) -> None:
    with pytest.raises(ValidationError):
        Money(rate=Decimal(rate), amount=Decimal(amount))
