"""Build a field support matrix across AirLLM and every provider request schema.

Flattens each provider's request schema into JSONPaths and reports, per path, which
providers accept it. Emits a CSV for spreadsheet use and a JSON blob for the HTML report.

    uv run python taxonomy/field_matrix.py [ingress] [maxdepth]

Paths come from the schema the provider actually publishes, so a provider that borrows the
canonical OpenAI schema reports OpenAI's fields verbatim. Those are flagged rather than
silently counted as evidence.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import TypedDict

from paths import TAXONOMY

import yaml

ROOT = TAXONOMY
OUT = ROOT / "reports"
INGRESS = sys.argv[1] if len(sys.argv) > 1 else "oai"
MAXDEPTH = int(sys.argv[2]) if len(sys.argv) > 2 else 2


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


def deref(node, defs, seen):
    hops = 0
    while isinstance(node, dict) and "$ref" in node and hops < 20:
        key = node["$ref"].removeprefix("#/$defs/")
        if key in seen:
            return None
        seen = seen | {key}
        node = defs.get(key)
        hops += 1
    return node


def expand(node, defs, seen, budget=40):
    """Every concrete object schema reachable from node through $ref and oneOf/anyOf/allOf.

    Composition nests: a oneOf branch is often an allOf of a shared base and an inline
    delta, so flattening only one level loses every field on those branches.
    """
    out, queue = [], [node]
    while queue and budget > 0:
        budget -= 1
        current = deref(queue.pop(), defs, seen)
        if not isinstance(current, dict):
            continue
        if current.get("properties") or current.get("items") is not None:
            out.append(current)
        for kw in ("oneOf", "anyOf", "allOf"):
            queue.extend(current.get(kw) or [])
    return out


def walk(node, defs, prefix, depth, acc, seen=frozenset()):
    if depth > MAXDEPTH:
        return
    for variant in expand(node, defs, seen):
        for name, sub in (variant.get("properties") or {}).items():
            path = f"{prefix}.{name}"
            acc.add(path)
            walk(sub, defs, path, depth + 1, acc, seen)
        if variant.get("items") is not None:
            walk(variant["items"], defs, f"{prefix}[*]", depth, acc, seen)


def paths_for(rel: str) -> set[str]:
    path = ROOT / rel
    doc = yaml.safe_load(path.read_text()) if path.suffix in {".yaml", ".yml"} else json.loads(path.read_text())
    defs = doc.get("$defs") or {}
    acc: set[str] = set()
    walk({k: v for k, v in doc.items() if k != "$defs"}, defs, "$", 0, acc)
    return acc


def main() -> int:
    providers = yaml.safe_load((ROOT / "providers.yml").read_text())["providers"]

    airllm_paths = paths_for("schemas/completion/airllm.request.yaml")
    columns = [{"id": "airllm", "name": "AirLLM", "kind": "gateway", "standin": False, "count": len(airllm_paths)}]
    support = {"airllm": airllm_paths}
    for entry in providers:
        parts = (entry["schema"] or {}).get("completion", {}).get(INGRESS)
        if not parts:
            continue
        support[entry["id"]] = paths_for(parts["request"])
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
        verified = sum(f for f, c in zip(flags, columns) if c["kind"] == "provider" and not c["standin"])
        rows.append({"path": path, "flags": flags, "total": sum(flags), "verified": verified})
    rows.sort(key=lambda r: (-r["total"], r["path"]))

    OUT.mkdir(exist_ok=True)
    csv_path = OUT / f"{INGRESS}-request-fields.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["jsonpath", "supported_by", "supported_by_excluding_standins"] + [c["id"] for c in columns])
        for r in rows:
            w.writerow([r["path"], r["total"], r["verified"]] + r["flags"])

    blob = {"ingress": INGRESS, "maxdepth": MAXDEPTH, "columns": columns, "rows": rows}
    (OUT / f"{INGRESS}-request-fields.json").write_text(json.dumps(blob, separators=(",", ":")) + "\n")

    universal = sum(1 for r in rows if r["total"] == len(columns))
    solo = sum(1 for r in rows if r["total"] == 1)
    print(f"ingress {INGRESS} | depth {MAXDEPTH}")
    print(f"  {len(columns)} columns ({sum(1 for c in columns if c['standin'])} canonical stand-ins), {len(rows)} paths")
    print(f"  universal: {universal} | single-column: {solo}")
    print(f"  wrote {csv_path} and {csv_path.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
