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

SEED = HERE.parent / "seed.yml"
CANON = {"oai": "openai", "anthropic": "anthropic"}
FIELD_ORDER = ("id", "name", "icon_mono", "icon_color", "homepage", "docs", "base_url",
               "openapi", "models_url", "ingress", "auth", "env_var", "schema")
# (provider, ingress) pairs that borrow the canonical schema because the vendor documents
# no parameters of its own for that surface
STANDIN = {(p, i) for p in ("nvidia", "hyperbolic", "lambda") for i in ("oai",)} | {
    (p, i) for p in ("baseten", "bedrock", "vertex") for i in ("oai", "anthropic")
} | {("deepseek", "anthropic"), ("minimax", "anthropic")}
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
    banner = (
        "# Provider catalog. Data only; every field is defined in the provider-catalog\n"
        "# skill, see .agents/skills/provider-catalog/references/fields.md\n\n"
    )
    path.write_text(banner + yaml.safe_dump({key: entries}, sort_keys=False, width=100, allow_unicode=True))
    print(f"  wrote {path.relative_to(TAXONOMY.parent)} ({len(entries)} entries)")


def run_with(script: str, *args: str) -> None:
    print(f"\n=== {script} {' '.join(args)}")
    result = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True)
    for line in (result.stdout or result.stderr).strip().splitlines()[-4:]:
        print(f"  {line}")


def run(script: str) -> None:
    print(f"\n=== {script}")
    result = subprocess.run([sys.executable, str(HERE / script)], capture_output=True, text=True)
    tail = (result.stdout or result.stderr).strip().splitlines()
    for line in tail[-6:]:
        print(f"  {line}")
    if result.returncode != 0:
        print(f"  ({script} exited {result.returncode})")


def main() -> int:
    seed = yaml.safe_load(SEED.read_text())
    TAXONOMY.mkdir(exist_ok=True)
    for sub in ("schemas/completion", "models", "icons", "reports"):
        (TAXONOMY / sub).mkdir(parents=True, exist_ok=True)

    print("restoring catalog files from seed")
    # written twice: once so the extractors can read openapi urls, once with real schemas
    for key in ("providers", "routers"):
        if key in seed:
            write_yaml(key, [dict(e) for e in seed[key]])

    if "--yaml" in sys.argv:
        return 0

    for script in ("extract_schemas.py", "doc_schemas.py", "fetch_icons.py",
                   "fetch_models.py", "enrich.py", "apply_parameter_docs.py"):
        run(script)

    print("\nrewiring schema references now that the extractors have run")
    for key in ("providers", "routers"):
        if key in seed:
            write_yaml(key, [dict(e) for e in seed[key]])

    for ingress in ("oai", "anthropic"):
        run_with("field_matrix.py", ingress)
    run("build_report.py")
    run("build_taxonomy.py")
    print()
    return subprocess.run([sys.executable, str(HERE / "validate.py")]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
