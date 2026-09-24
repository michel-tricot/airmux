"""Restore catalog definitions from seed.yml and acquired schema references.

The outer CLI coordinates the remaining derivation steps for a full rebuild.

    uv run airmux-audit taxonomy rebuild

Schemas are wired up from what the extractors actually produced, so a vendor that has
since removed or moved its spec yields a smaller catalog rather than a broken one.
"""

from __future__ import annotations

import yaml

from model_audit.catalog_ops import CANDIDATES_HEADER, PROVIDERS_HEADER, provider_entry

from .outcomes import CatalogFile, CatalogRestored, MissingProviderSourceError
from .paths import TAXONOMY
from .sources import registry

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


def write_yaml(key: str, entries: list[dict]) -> CatalogFile:
    for entry in entries:
        entry["schema"] = schema_block(entry)
    entries = [{k: e[k] for k in FIELD_ORDER if k in e} for e in entries]
    path = TAXONOMY / f"{key.rstrip('s')}s.yml"
    banner = PROVIDERS_HEADER
    path.write_text(banner + yaml.safe_dump({key: entries}, sort_keys=False, width=100, allow_unicode=True))
    return CatalogFile(path, len(entries))


def write_candidates(entries: list[dict]) -> CatalogFile:
    path = TAXONOMY / "candidates.yml"
    path.write_text(CANDIDATES_HEADER + yaml.safe_dump({"candidates": entries}, sort_keys=False, width=100, allow_unicode=True))
    return CatalogFile(path, len(entries))


def current_provider_entries(entries: list[dict]) -> list[dict]:
    sources = registry()
    current = []
    for entry in entries:
        source = sources.get(entry["id"])
        if source is None or source.definition is None:
            raise MissingProviderSourceError(entry["id"])
        current.append(provider_entry(source.definition))
    return current


def run(*, include_candidates: bool = True) -> CatalogRestored:
    seed = yaml.safe_load(SEED.read_text())
    seed["providers"] = current_provider_entries(seed.get("providers", []))
    TAXONOMY.mkdir(exist_ok=True)
    for subdirectory in ("schemas/completion", "models", "icons", "reports"):
        (TAXONOMY / subdirectory).mkdir(parents=True, exist_ok=True)
    files = tuple(write_yaml(key, [dict(entry) for entry in seed[key]]) for key in ("providers", "routers") if key in seed)
    if include_candidates and "candidates" in seed:
        files += (write_candidates([dict(entry) for entry in seed["candidates"]]),)
    return CatalogRestored(files)
