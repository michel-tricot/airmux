from __future__ import annotations

import json
from typing import TYPE_CHECKING

from model_audit.catalog_ops import load_provider_entries

from .canonical import write_catalog
from .output import emit
from .parameter_support import apply_discovery_evidence, discovery_evidence
from .paths import TAXONOMY

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(arguments: Sequence[str] = ()) -> int:
    providers = load_provider_entries(TAXONOMY)
    changed = 0
    classified = 0
    available = sorted(path.stem for path in (TAXONOMY / "models").glob("*.json"))
    selected = set(arguments)
    unknown = selected - set(available)
    if unknown:
        emit(f"not in taxonomy/models: {sorted(unknown)}")
        return 2
    catalogued = sorted(selected) if selected else available
    for path in (TAXONOMY / "models" / f"{provider}.json" for provider in catalogued):
        catalog = json.loads(path.read_text())
        provider = providers[catalog["provider"]]
        models = apply_discovery_evidence(catalog["models"], discovery_evidence(provider, TAXONOMY))
        classified += len(models)
        changed += write_catalog(path, {**catalog, "models": models})
    emit(f"parameter support discovered for {classified} models; {changed} catalogs changed")
    return 0
