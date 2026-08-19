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

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from catalog_io import atomic_write_text
from paths import TAXONOMY
from refresh import publish

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
    "models_auth",
    "models_headers",
    "ingress",
    "surfaces",
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
    banner = (
        "# Provider catalog. Data only; every field is defined in the provider-catalog\n"
        "# skill, see .agents/skills/provider-catalog/references/fields.md\n\n"
    )
    atomic_write_text(path, banner + yaml.safe_dump({key: entries}, sort_keys=False, width=100, allow_unicode=True))
    print(f"  wrote {path.relative_to(TAXONOMY.parent)} ({len(entries)} entries)")


def run_with(script: str, *args: str) -> None:
    print(f"\n=== {script} {' '.join(args)}")
    result = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True, check=True)
    for line in (result.stdout or result.stderr).strip().splitlines()[-4:]:
        print(f"  {line}")


def run(script: str) -> None:
    print(f"\n=== {script}")
    result = subprocess.run([sys.executable, str(HERE / script)], capture_output=True, text=True, check=True)
    tail = (result.stdout or result.stderr).strip().splitlines()
    for line in tail[-6:]:
        print(f"  {line}")


def execute(yaml_only: bool, confirmed: bool) -> None:
    seed = yaml.safe_load(SEED.read_text())
    TAXONOMY.mkdir(exist_ok=True)
    for sub in ("schemas/completion", "models", "icons", "reports"):
        (TAXONOMY / sub).mkdir(parents=True, exist_ok=True)

    print("restoring catalog files from seed")
    # written twice: once so the extractors can read openapi urls, once with real schemas
    for key in ("providers", "routers"):
        if key in seed:
            write_yaml(key, [dict(e) for e in seed[key]])

    if yaml_only:
        return

    for script in (
        "extract_schemas.py",
        "doc_schemas.py",
        "fetch_icons.py",
        "fetch_models.py",
        "enrich.py",
        "discover_parameters.py",
        "discover_capabilities.py",
    ):
        run(script)

    confirmation = ("--yes",) if confirmed else ()
    run_with("smoke.py", *confirmation)
    run_with("probe_capabilities.py", "--replace", *confirmation)
    run_with("probe_parameters.py", "--replace", *confirmation)

    print("\nrewiring schema references now that the extractors have run")
    for key in ("providers", "routers"):
        if key in seed:
            write_yaml(key, [dict(e) for e in seed[key]])

    for ingress in ("oai", "anthropic"):
        run_with("field_matrix.py", ingress)
    run("build_report.py")
    run("build_taxonomy.py")
    run("validate.py")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transactionally rebuild taxonomy from the provider-catalog seed")
    parser.add_argument("--yaml", action="store_true", help="Restore provider YAML only")
    parser.add_argument("--yes", action="store_true", help="Confirm probe runs above their request guardrails")
    parser.add_argument("--in-place", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main() -> int:
    arguments = parse_args()
    if arguments.in_place:
        execute(arguments.yaml, arguments.yes)
        return 0
    with tempfile.TemporaryDirectory(prefix="airllm-taxonomy-bootstrap-") as temporary:
        staged = Path(temporary) / "taxonomy"
        environment = {**os.environ, "AIRLLM_TAXONOMY_ROOT": str(staged)}
        command = [sys.executable, str(Path(__file__).resolve()), "--in-place"]
        if arguments.yaml:
            command.append("--yaml")
        if arguments.yes:
            command.append("--yes")
        try:
            subprocess.run(command, check=True, env=environment)
        except subprocess.CalledProcessError as exc:
            print("bootstrap failed; the live catalog was not changed", file=sys.stderr)
            return exc.returncode or 1
        publish(staged, TAXONOMY)
    print("published validated bootstrap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
