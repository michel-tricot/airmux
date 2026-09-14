"""Build a field support matrix across TokKeeper and every provider request schema.

Flattens each provider's request schema into JSONPaths and reports, per path, which
providers accept it. Emits a CSV for spreadsheet use and a JSON blob for the HTML report.

    Generated as part of `uv run tokkeeper-audit taxonomy rebuild`.

Paths come from the schema the provider actually publishes, so a provider that borrows the
canonical OpenAI schema reports OpenAI's fields verbatim. Those are flagged rather than
silently counted as evidence.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import yaml

from .output import emit
from .paths import TAXONOMY
from .types import is_object, object_or_empty, string, value_list

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .types import CatalogObject, CatalogValue

ROOT = TAXONOMY
OUT = ROOT / "reports"
MAX_REFERENCE_HOPS = 20
DEFAULT_MAX_DEPTH = 2


def is_standin(entry_id: str, request_path: str) -> bool:
    """A column is a restatement when the schema it points at belongs to someone else.

    Filenames are <ingress>.<owner>.<part>.json, so the owner is on the file rather than in
    a list kept in step by hand. A provider pointing at oai.openai.* or anthropic.anthropic.*
    is echoing the canonical shape, and its agreement is one fact repeated, not evidence.

    Reading it off the path also gets the mixed case right, which a set of provider ids
    cannot express: deepseek documents its own oai parameters and borrows anthropic's, so it
    is evidence in one column and a stand-in in the other.
    """
    return Path(request_path).name.split(".")[1] != entry_id


class MatrixRow(TypedDict):
    path: str
    flags: list[int]
    total: int
    verified: int


def deref(node: CatalogValue, definitions: Mapping[str, CatalogValue], seen: frozenset[str]) -> CatalogValue:
    hops = 0
    while is_object(node) and hops < MAX_REFERENCE_HOPS:
        reference = string(node.get("$ref"))
        if reference is None:
            break
        key = reference.removeprefix("#/$defs/")
        if key in seen:
            return None
        seen = seen | {key}
        node = definitions.get(key)
        hops += 1
    return node


def expand(node: CatalogValue, definitions: Mapping[str, CatalogValue], seen: frozenset[str], budget: int = 40) -> list[CatalogObject]:
    """Every concrete object schema reachable from node through $ref and oneOf/anyOf/allOf.

    Composition nests: a oneOf branch is often an allOf of a shared base and an inline
    delta, so flattening only one level loses every field on those branches.
    """
    out, queue = [], [node]
    while queue and budget > 0:
        budget -= 1
        current = deref(queue.pop(), definitions, seen)
        if not is_object(current):
            continue
        if current.get("properties") or current.get("items") is not None:
            out.append(current)
        for kw in ("oneOf", "anyOf", "allOf"):
            queue.extend(value_list(current.get(kw)))
    return out


def walk(  # noqa: PLR0913,PLR0917 recursive schema traversal keeps its state explicit
    node: CatalogValue,
    definitions: Mapping[str, CatalogValue],
    prefix: str,
    depth: int,
    paths: set[str],
    max_depth: int,
    seen: frozenset[str] = frozenset(),
) -> None:
    if depth > max_depth:
        return
    for variant in expand(node, definitions, seen):
        for name, sub in object_or_empty(variant.get("properties")).items():
            path = f"{prefix}.{name}"
            paths.add(path)
            walk(sub, definitions, path, depth + 1, paths, max_depth, seen)
        if variant.get("items") is not None:
            walk(variant["items"], definitions, f"{prefix}[*]", depth, paths, max_depth, seen)


def paths_for(rel: str, max_depth: int) -> set[str]:
    path = ROOT / rel
    doc = yaml.safe_load(path.read_text()) if path.suffix in {".yaml", ".yml"} else json.loads(path.read_text())
    defs = doc.get("$defs") or {}
    acc: set[str] = set()
    walk({k: v for k, v in doc.items() if k != "$defs"}, defs, "$", 0, acc, max_depth)
    return acc


def main(arguments: Sequence[str] = ()) -> int:
    ingress = arguments[0] if arguments else "oai"
    max_depth = int(arguments[1]) if len(arguments) > 1 else DEFAULT_MAX_DEPTH
    providers = yaml.safe_load((ROOT / "providers.yml").read_text())["providers"]

    tokkeeper_paths = paths_for("schemas/completion/tokkeeper.request.yaml", max_depth)
    columns = [{"id": "tokkeeper", "name": "TokKeeper", "kind": "gateway", "standin": False, "count": len(tokkeeper_paths)}]
    support = {"tokkeeper": tokkeeper_paths}
    for entry in providers:
        parts = (entry["schema"] or {}).get("completion", {}).get(ingress)
        if not parts:
            continue
        support[entry["id"]] = paths_for(parts["request"], max_depth)
        columns.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "kind": "provider",
                "standin": is_standin(entry["id"], parts["request"]),
                "count": len(support[entry["id"]]),
            }
        )

    paths = sorted(set().union(*support.values()))
    rows: list[MatrixRow] = []
    for path in paths:
        flags = [1 if path in support[c["id"]] else 0 for c in columns]
        verified = sum(f for f, c in zip(flags, columns, strict=True) if c["kind"] == "provider" and not c["standin"])
        rows.append({"path": path, "flags": flags, "total": sum(flags), "verified": verified})
    rows.sort(key=lambda r: (-r["total"], r["path"]))

    OUT.mkdir(exist_ok=True)
    csv_path = OUT / f"{ingress}-request-fields.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["jsonpath", "supported_by", "supported_by_excluding_standins"] + [c["id"] for c in columns])
        for r in rows:
            w.writerow([r["path"], r["total"], r["verified"]] + r["flags"])

    blob = {"ingress": ingress, "maxdepth": max_depth, "columns": columns, "rows": rows}
    (OUT / f"{ingress}-request-fields.json").write_text(json.dumps(blob, separators=(",", ":")) + "\n")

    universal = sum(1 for r in rows if r["total"] == len(columns))
    solo = sum(1 for r in rows if r["total"] == 1)
    emit(f"ingress {ingress} | depth {max_depth}")
    emit(f"  {len(columns)} columns ({sum(1 for c in columns if c['standin'])} canonical stand-ins), {len(rows)} paths")
    emit(f"  universal: {universal} | single-column: {solo}")
    emit(f"  wrote {csv_path} and {csv_path.with_suffix('.json')}")
    return 0
