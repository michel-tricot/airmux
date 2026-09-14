from __future__ import annotations

from typing import TypeGuard, cast

type CatalogValue = object
type CatalogObject = dict[str, object]


def is_object(value: object) -> TypeGuard[CatalogObject]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def object_or_empty(value: object) -> CatalogObject:
    return value if is_object(value) else {}


def object_list(value: object) -> list[CatalogObject]:
    return [item for item in value if is_object(item)] if isinstance(value, list) else []


def value_list(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


def string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def required_string(value: object, field: str) -> str:
    if result := string(value):
        return result
    message = f"{field} must be a non-empty string"
    raise ValueError(message)


def strings(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def number(value: object) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def boolean(value: object) -> bool | None:
    return value if isinstance(value, bool) else None
