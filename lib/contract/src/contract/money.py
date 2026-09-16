from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, Field, PlainSerializer, WithJsonSchema

_DECIMAL_PATTERN = re.compile(r"\d+(?:\.\d+)?\Z")
_MONEY_SCHEMA = {"type": "string", "pattern": r"^\d+(?:\.\d+)?$"}


def parse_fixed_point(value: str) -> Decimal:
    if not _DECIMAL_PATTERN.fullmatch(value):
        message = "money must be a finite fixed-point decimal string"
        raise ValueError(message)
    return Decimal(value)


def _exact_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        if value.is_finite():
            return value
    elif isinstance(value, str):
        return parse_fixed_point(value)
    message = "money must be a finite fixed-point decimal string"
    raise ValueError(message)


def fixed_point(value: Decimal) -> str:
    return format(value, "f")


def _precision(value: Decimal, *, digits: int, scale: int) -> Decimal:
    _, coefficient, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        message = "money must be finite"
        raise TypeError(message)
    decimal_places = max(-exponent, 0)
    whole_digits = max(len(coefficient) + exponent, 0)
    if decimal_places > scale or whole_digits > digits - scale:
        message = f"money must have at most {digits - scale} whole digits and {scale} decimal places"
        raise ValueError(message)
    return value


def _rate_precision(value: Decimal) -> Decimal:
    return _precision(value, digits=16, scale=6)


def _amount_precision(value: Decimal) -> Decimal:
    return _precision(value, digits=28, scale=12)


UsdRate = Annotated[
    Decimal,
    BeforeValidator(_exact_decimal),
    AfterValidator(_rate_precision),
    Field(ge=0, max_digits=16, decimal_places=6),
    PlainSerializer(fixed_point, return_type=str, when_used="json"),
    WithJsonSchema(_MONEY_SCHEMA),
]
UsdAmount = Annotated[
    Decimal,
    BeforeValidator(_exact_decimal),
    AfterValidator(_amount_precision),
    Field(ge=0, max_digits=28, decimal_places=12),
    PlainSerializer(fixed_point, return_type=str, when_used="json"),
    WithJsonSchema(_MONEY_SCHEMA),
]

ZERO_USD = Decimal(0)
USD_AMOUNT_QUANTUM = Decimal("0.000000000001")
