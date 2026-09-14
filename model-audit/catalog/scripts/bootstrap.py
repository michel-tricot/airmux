"""Rebuild taxonomy/ from seed.yml, assuming the directory does not exist.

Restores providers.yml and routers.yml from the seed, then runs the derivation chain that
produces everything else. What comes back is the whole catalog minus the prose headers,
which are documentation rather than data and live in git.

    uv run python bootstrap.py            rebuild everything
    uv run python bootstrap.py --yaml     restore the two YAML files only

Schemas are wired up from what the extractors actually produced, so a vendor that has
since removed or moved its spec yields a smaller catalog rather than a broken one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from paths import TAXONOMY
from sources import registry

from model_audit.catalog_ops import CANDIDATES_HEADER, PROVIDERS_HEADER, provider_entry
from model_audit.taxonomy import write as write_taxonomy

SEED = HERE.parent / "seed.yml"
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
    print(f"  wrote {path.relative_to(TAXONOMY.parent)} ({len(entries)} entries)")


def write_candidates(entries: list[dict]) -> None:
    path = TAXONOMY / "candidates.yml"
    path.write_text(CANDIDATES_HEADER + yaml.safe_dump({"candidates": entries}, sort_keys=False, width=100, allow_unicode=True))
    print(f"  wrote {path.relative_to(TAXONOMY.parent)} ({len(entries)} entries)")


def current_provider_entries(entries: list[dict]) -> list[dict]:
    sources = registry()
    current = []
    for entry in entries:
        source = sources.get(entry["id"])
        if source is None or source.definition is None:
            raise RuntimeError(f"active provider {entry['id']} has no typed provider source")
        current.append(provider_entry(source.definition))
    return current


def run_command(command: list[str]) -> int:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    for line in (result.stdout or result.stderr).strip().splitlines()[-6:]:
        print(f"  {line}")
    if result.returncode != 0:
        print(f"  (exited {result.returncode})")
    return result.returncode


def run_with(script: str, *args: str) -> int:
    print(f"\n=== {script} {' '.join(args)}")
    return run_command([sys.executable, str(HERE / script), *args])


def run(script: str) -> int:
    print(f"\n=== {script}")
    return run_command([sys.executable, str(HERE / script)])


def export_canonical_schemas() -> int:
    executable = Path(sys.executable).with_name("tokkeeperdp")
    print("\n=== tokkeeperdp schema")
    return run_command([str(executable), "schema", "--out", str(TAXONOMY / "schemas" / "completion")])


def main() -> int:
    seed = yaml.safe_load(SEED.read_text())
    seed["providers"] = current_provider_entries(seed.get("providers", []))
    TAXONOMY.mkdir(exist_ok=True)
    for sub in ("schemas/completion", "models", "icons", "reports"):
        (TAXONOMY / sub).mkdir(parents=True, exist_ok=True)

    print("restoring catalog files from seed")
    for key in ("providers", "routers"):
        if key in seed:
            write_yaml(key, [dict(e) for e in seed[key]])
    if "candidates" in seed:
        write_candidates([dict(entry) for entry in seed["candidates"]])

    if "--yaml" in sys.argv:
        return 0

    if run("make_seed.py") or export_canonical_schemas():
        return 1
    for script in ("extract_schemas.py", "doc_schemas.py"):
        if run(script):
            return 1

    print("\nwriting acquired schema references")
    for key in ("providers", "routers"):
        if key in seed:
            write_yaml(key, [dict(e) for e in seed[key]])

    for script in ("fetch_icons.py", "fetch_models.py", "enrich.py", "discover_parameters.py"):
        if run(script):
            return 1

    for ingress in ("oai", "anthropic"):
        if run_with("field_matrix.py", ingress):
            return 1
    if run("build_report.py"):
        return 1
    write_taxonomy(TAXONOMY.parent)
    print()
    return run_command([sys.executable, str(HERE / "validate.py")])


if __name__ == "__main__":
    raise SystemExit(main())
