"""Deterministic serialization, so these files can be reviewed in a diff.

Every artefact under taxonomy/ is regenerated wholesale from live sources. Without a
canonical form a rerun reshuffles keys and reorders lists that vendors return arbitrarily,
and the diff is thousands of lines of noise hiding the one real change.

  key order    fixed, by meaning rather than alphabet, so the important fields lead
  list order   sorted by a stable key, never by whatever the vendor returned
  timestamps   only advance when something else in the document also changed

The last matters most in review: a stamp that moves on every run makes every file look
modified daily, which trains a reviewer to skim past the diffs worth reading.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING

from .types import object_list, object_or_empty

if TYPE_CHECKING:
    from pathlib import Path

    from .types import CatalogObject, CatalogValue

# Leading fields first, by how much a reader needs them. Anything unlisted sorts after,
# alphabetically, so a new field cannot silently land in the middle of an existing diff.
# "updated" is the date this content last changed, not the date it was last checked. A
# last-checked field would move every run and drown the diff; the catalog deliberately does
# not record it.
CATALOG_ORDER = ("provider", "source", "source_type", "updated", "count", "models")
MODEL_ORDER = (
    "id",
    "upstream_id",
    "kind",
    "context_length",
    "max_output_tokens",
    "input_modalities",
    "output_modalities",
    "supports_tools",
    "supports_structured_output",
    "pricing",
    "context_source",
    "max_output_source",
    "pricing_source",
    "parameter_evidence",
)


def order_keys(record: CatalogObject, leading: tuple[str, ...]) -> CatalogObject:
    known = [k for k in leading if k in record]
    rest = sorted(k for k in record if k not in leading)
    return {k: record[k] for k in known + rest}


def _contains_float(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_float(item) for item in value)
    return isinstance(value, float)


def validate_prices(record: CatalogObject) -> CatalogObject:
    pricing = record.get("pricing")
    if isinstance(pricing, dict) and _contains_float(pricing):
        message = "catalog pricing must use exact decimals"
        raise TypeError(message)
    return record


def sort_models(models: list[CatalogObject]) -> list[CatalogObject]:
    """Vendors return catalogs in arbitrary and unstable order. Impose one."""
    return sorted((validate_prices(order_keys(m, MODEL_ORDER)) for m in models), key=lambda m: (str(m.get("id", "")).lower(), str(m.get("id", ""))))


def sort_defs(schema: CatalogObject) -> CatalogObject:
    """$defs insertion order follows traversal order, an implementation detail."""
    if "$defs" in schema:
        definitions = object_or_empty(schema["$defs"])
        schema["$defs"] = {key: definitions[key] for key in sorted(definitions)}
    return schema


def _json(value: object, indent: int = 0) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        if not value:
            return "{}"
        entries = [f"{' ' * (indent + 2)}{json.dumps(str(key), ensure_ascii=False)}: {_json(item, indent + 2)}" for key, item in value.items()]
        return "{\n" + ",\n".join(entries) + f"\n{' ' * indent}}}"
    if isinstance(value, list):
        if not value:
            return "[]"
        entries = [f"{' ' * (indent + 2)}{_json(item, indent + 2)}" for item in value]
        return "[\n" + ",\n".join(entries) + f"\n{' ' * indent}]"
    return json.dumps(value, ensure_ascii=False)


def dumps(value: CatalogValue) -> str:
    return _json(value) + "\n"


def write_json(path: Path, value: CatalogValue, *, stamp_field: str | None = None) -> bool:
    """Write obj, keeping stamp_field when nothing else changed. True if the file moved."""
    text = dumps(value)
    if path.exists():
        previous = path.read_text()
        if previous == text:
            return False
        if stamp_field and isinstance(value, dict) and stamp_field in value:
            try:
                old = json.loads(previous, parse_float=Decimal)
            except json.JSONDecodeError:
                old = None
            if isinstance(old, dict) and stamp_field in old and dumps({**value, stamp_field: old[stamp_field]}) == previous:
                return False
    path.write_text(text)
    return True


def write_catalog(path: Path, document: CatalogObject) -> bool:
    models = sort_models(object_list(document.get("models")))
    document["models"] = models
    document["count"] = len(models)
    return write_json(path, order_keys(document, CATALOG_ORDER), stamp_field="updated")


def write_schema(path: Path, schema: CatalogObject) -> bool:
    return write_json(path, sort_defs(schema))
