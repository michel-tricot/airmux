"""Rebuild taxonomy/ from seed.yml, assuming the directory does not exist.

Restores providers.yml and routers.yml from the seed, then runs the derivation chain that
produces everything else. What comes back is the whole catalog minus the prose headers,
which are documentation rather than data and live in git.

    uv run tokkeeper-audit taxonomy rebuild

Schemas are wired up from what the extractors actually produced, so a vendor that has
since removed or moved its spec yields a smaller catalog rather than a broken one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from model_audit.catalog_ops import CANDIDATES_HEADER, PROVIDERS_HEADER, provider_entry
from model_audit.taxonomy import write as write_taxonomy

from . import build_report, discover_parameters, doc_schemas, enrich, extract_schemas, fetch_icons, fetch_models, field_matrix, make_seed, validate
from .output import emit
from .paths import TAXONOMY
from .sources import registry

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

SEED = TAXONOMY.parent / "model-audit" / "catalog" / "seed.yml"
CANON = {"oai": "openai", "anthropic": "anthropic"}
FIELD_ORDER = (
    "id",
    "name",
    "icon_mono",
    "icon_color",
    "homepage",
    "docs",
    "base_url",
    "openapi",
    "models_url",
    "ingress",
    "auth",
    "env_var",
    "schema",
)
# (provider, ingress) pairs that borrow the canonical schema because the vendor documents
# no parameters of its own for that surface
STANDIN = (
    {(p, i) for p in ("nvidia", "hyperbolic", "lambda") for i in ("oai",)}
    | {(p, i) for p in ("baseten", "bedrock", "vertex") for i in ("oai", "anthropic")}
    | {("deepseek", "anthropic"), ("minimax", "anthropic")}
)
WIRE = ("oai", "oai_responses", "anthropic", "custom")


def schema_block(entry: dict) -> dict | None:
    """Point each wire ingress at whichever parts the extractors actually wrote."""
    completion = {}
    for ingress in WIRE:
        if ingress not in entry["ingress"]:
            continue
        owner = CANON[ingress] if (entry["id"], ingress) in STANDIN else entry["id"]
        parts = {}
        for part in ("request", "response", "stream"):
            name = f"{ingress}.{owner}.{part}.json"
            if (TAXONOMY / "schemas" / "completion" / name).exists():
                parts[part] = f"schemas/completion/{name}"
        if parts:
            completion[ingress] = parts
    return {"completion": completion} if completion else None


def write_yaml(key: str, entries: list[dict]) -> None:
    for entry in entries:
        entry["schema"] = schema_block(entry)
    entries = [{k: e[k] for k in FIELD_ORDER if k in e} for e in entries]
    path = TAXONOMY / f"{key.rstrip('s')}s.yml"
    banner = PROVIDERS_HEADER
    path.write_text(banner + yaml.safe_dump({key: entries}, sort_keys=False, width=100, allow_unicode=True))
    emit(f"  wrote {path.relative_to(TAXONOMY.parent)} ({len(entries)} entries)")


def write_candidates(entries: list[dict]) -> None:
    path = TAXONOMY / "candidates.yml"
    path.write_text(CANDIDATES_HEADER + yaml.safe_dump({"candidates": entries}, sort_keys=False, width=100, allow_unicode=True))
    emit(f"  wrote {path.relative_to(TAXONOMY.parent)} ({len(entries)} entries)")


def current_provider_entries(entries: list[dict]) -> list[dict]:
    sources = registry()
    current = []
    for entry in entries:
        source = sources.get(entry["id"])
        if source is None or source.definition is None:
            message = f"active provider {entry['id']} has no typed provider source"
            raise RuntimeError(message)
        current.append(provider_entry(source.definition))
    return current


def run_command(command: list[str]) -> int:
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603 fixed data-plane schema command
    for line in (result.stdout or result.stderr).strip().splitlines()[-6:]:
        emit(f"  {line}")
    if result.returncode != 0:
        emit(f"  (exited {result.returncode})")
    return result.returncode


def run_task(name: str, task: Callable[[Sequence[str]], int], *arguments: str) -> int:
    emit(f"\n=== {name} {' '.join(arguments)}".rstrip())
    return task(arguments)


def export_canonical_schemas() -> int:
    executable = Path(sys.executable).with_name("tokkeeper")
    emit("\n=== tokkeeper gateway schema")
    return run_command([str(executable), "gateway", "schema", "--out", str(TAXONOMY / "schemas" / "completion")])


def derive(seed: dict) -> int:
    if run_task("make_seed", make_seed.main) or export_canonical_schemas():
        return 1
    for name, task in (("extract_schemas", extract_schemas.main), ("doc_schemas", doc_schemas.main)):
        if run_task(name, task):
            return 1

    emit("\nwriting acquired schema references")
    for key in ("providers", "routers"):
        if key in seed:
            write_yaml(key, [dict(e) for e in seed[key]])

    for name, task in (
        ("fetch_icons", fetch_icons.main),
        ("fetch_models", fetch_models.main),
        ("enrich", enrich.main),
        ("discover_parameters", discover_parameters.main),
    ):
        if run_task(name, task):
            return 1

    for ingress in ("oai", "anthropic"):
        if run_task("field_matrix", field_matrix.main, ingress):
            return 1
    if run_task("build_report", build_report.main):
        return 1
    write_taxonomy(TAXONOMY.parent)
    emit()
    return run_task("validate", validate.main)


def main(arguments: Sequence[str] = ()) -> int:
    seed = yaml.safe_load(SEED.read_text())
    seed["providers"] = current_provider_entries(seed.get("providers", []))
    TAXONOMY.mkdir(exist_ok=True)
    for subdirectory in ("schemas/completion", "models", "icons", "reports"):
        (TAXONOMY / subdirectory).mkdir(parents=True, exist_ok=True)

    emit("restoring catalog files from seed")
    for key in ("providers", "routers"):
        if key in seed:
            write_yaml(key, [dict(entry) for entry in seed[key]])
    if "candidates" in seed:
        write_candidates([dict(entry) for entry in seed["candidates"]])

    return 0 if "--yaml" in arguments else derive(seed)
