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
from pathlib import Path
from typing import Any

# Leading fields first, by how much a reader needs them. Anything unlisted sorts after,
# alphabetically, so a new field cannot silently land in the middle of an existing diff.
# "updated" is the date this content last changed, not the date it was last checked. A
# last-checked field would move every run and drown the diff; the catalog deliberately does
# not record it.
CATALOG_ORDER = ("provider", "source", "source_type", "updated", "count", "models")
MODEL_ORDER = (
    "id", "upstream_id", "kind", "context_length", "max_output_tokens",
    "input_modalities", "output_modalities",
    "supports_tools", "supports_structured_output", "pricing",
    "limits_source", "pricing_source", "reachable", "reachable_checked",
    "parameter_evidence",
)


def order_keys(record: dict, leading: tuple[str, ...]) -> dict:
    known = [k for k in leading if k in record]
    rest = sorted(k for k in record if k not in leading)
    return {k: record[k] for k in known + rest}


def clean_floats(record: dict) -> dict:
    """Round money to the cent-per-million. Vendors return binary float noise like
    0.030000000000000002, which is meaningless precision and pure diff churn."""
    pricing = record.get("pricing")
    if isinstance(pricing, dict):
        record["pricing"] = {
            k: round(v, 4) if isinstance(v, float) else v for k, v in pricing.items()
        }
    return record


def sort_models(models: list[dict]) -> list[dict]:
    """Vendors return catalogs in arbitrary and unstable order. Impose one."""
    return sorted((clean_floats(order_keys(m, MODEL_ORDER)) for m in models),
                  key=lambda m: (str(m.get("id", "")).lower(), str(m.get("id", ""))))


def sort_defs(schema: dict) -> dict:
    """$defs insertion order follows traversal order, an implementation detail."""
    if "$defs" in schema:
        schema["$defs"] = {k: schema["$defs"][k] for k in sorted(schema["$defs"])}
    return schema


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def write_json(path: Path, obj: Any, *, stamp_field: str | None = None) -> bool:
    """Write obj, keeping stamp_field when nothing else changed. True if the file moved."""
    text = dumps(obj)
    if path.exists():
        previous = path.read_text()
        if previous == text:
            return False
        if stamp_field and isinstance(obj, dict) and stamp_field in obj:
            try:
                old = json.loads(previous)
            except json.JSONDecodeError:
                old = None
            if isinstance(old, dict) and stamp_field in old:
                if dumps({**obj, stamp_field: old[stamp_field]}) == previous:
                    return False
    path.write_text(text)
    return True


def write_catalog(path: Path, doc: dict) -> bool:
    doc["models"] = sort_models(doc.get("models") or [])
    doc["count"] = len(doc["models"])
    return write_json(path, order_keys(doc, CATALOG_ORDER), stamp_field="updated")


def write_schema(path: Path, schema: dict) -> bool:
    return write_json(path, sort_defs(schema))
