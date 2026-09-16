from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path


def _indexed(path: Path, key: str, identity: str) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    document = (
        yaml.safe_load(path.read_text(encoding="utf-8"))
        if path.suffix in {".yml", ".yaml"}
        else json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    )
    return {str(item[identity]): item for item in document.get(key, [])}


def _value(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_value(item) for item in value]
    return value


def _records(scope: str, provider: str, before: dict[str, object] | None, after: dict[str, object] | None) -> list[dict[str, object]]:
    if before is None or after is None:
        return [
            {
                "scope": scope,
                "provider": provider,
                "model": "",
                "field": "$record",
                "change": "added" if before is None else "removed",
                "before": _value(before),
                "after": _value(after),
            }
        ]
    return [
        {
            "scope": scope,
            "provider": provider,
            "model": "",
            "field": field,
            "change": "changed",
            "before": _value(before.get(field)),
            "after": _value(after.get(field)),
        }
        for field in sorted(set(before) | set(after))
        if before.get(field) != after.get(field)
    ]


def _model_records(scope: str, provider: str, before: dict[str, dict[str, object]], after: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for model_id in sorted(set(before) | set(after)):
        old = before.get(model_id)
        new = after.get(model_id)
        if old is None or new is None:
            rows.append(
                {
                    "scope": scope,
                    "provider": provider,
                    "model": model_id,
                    "field": "$record",
                    "change": "added" if old is None else "removed",
                    "before": _value(old),
                    "after": _value(new),
                }
            )
            continue
        rows.extend(
            {
                "scope": scope,
                "provider": provider,
                "model": model_id,
                "field": field,
                "change": "changed",
                "before": _value(old.get(field)),
                "after": _value(new.get(field)),
            }
            for field in sorted(set(old) | set(new))
            if old.get(field) != new.get(field)
        )
    return rows


def _file_records(before: Path, after: Path, directory: str) -> list[dict[str, object]]:
    old = {path.relative_to(before).as_posix(): path for path in (before / directory).rglob("*") if path.is_file()}
    new = {path.relative_to(after).as_posix(): path for path in (after / directory).rglob("*") if path.is_file()}
    rows: list[dict[str, object]] = []
    for name in sorted(set(old) | set(new)):
        old_digest = hashlib.sha256(old[name].read_bytes()).hexdigest() if name in old else None
        new_digest = hashlib.sha256(new[name].read_bytes()).hexdigest() if name in new else None
        if old_digest == new_digest:
            continue
        rows.append(
            {
                "scope": directory.rstrip("s"),
                "provider": "",
                "model": name,
                "field": "sha256",
                "change": "added" if old_digest is None else "removed" if new_digest is None else "changed",
                "before": old_digest,
                "after": new_digest,
            }
        )
    return rows


def compare_taxonomies(before: Path, after: Path) -> list[dict[str, object]]:
    old_providers = _indexed(before / "providers.yml", "providers", "id")
    new_providers = _indexed(after / "providers.yml", "providers", "id")
    rows = [
        row
        for provider in sorted(set(old_providers) | set(new_providers))
        for row in _records("provider", provider, old_providers.get(provider), new_providers.get(provider))
    ]
    for provider in sorted({path.stem for path in (before / "models").glob("*.json")} | {path.stem for path in (after / "models").glob("*.json")}):
        old_models = _indexed(before / "models" / f"{provider}.json", "models", "id")
        new_models = _indexed(after / "models" / f"{provider}.json", "models", "id")
        rows.extend(_model_records("catalog-model", provider, old_models, new_models))
    old_applied = _indexed(before / "taxonomy.yml", "models", "model_id")
    new_applied = _indexed(after / "taxonomy.yml", "models", "model_id")
    rows.extend(_model_records("applied-model", "", old_applied, new_applied))
    rows.extend(_file_records(before, after, "schemas"))
    rows.extend(_file_records(before, after, "icons"))
    return rows


def summarize_taxonomy_diff(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    keys = sorted({(str(row["scope"]), str(row["change"])) for row in rows})
    return [
        {"scope": scope, "change": change, "count": sum(row["scope"] == scope and row["change"] == change for row in rows)} for scope, change in keys
    ]
