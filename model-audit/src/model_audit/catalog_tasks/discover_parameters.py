from __future__ import annotations

import json
from decimal import Decimal

from model_audit.catalog_ops import load_provider_entries

from .canonical import write_catalog
from .outcomes import ParametersDiscovered, UnknownProvidersError
from .parameter_support import apply_discovery_evidence, discovery_evidence
from .paths import TAXONOMY


def run(providers: tuple[str, ...] = ()) -> ParametersDiscovered:
    entries = load_provider_entries(TAXONOMY)
    changed = 0
    classified = 0
    available = sorted(path.stem for path in (TAXONOMY / "models").glob("*.json"))
    selected = set(providers)
    unknown = selected - set(available)
    if unknown:
        raise UnknownProvidersError(unknown, "taxonomy/models")
    catalogued = sorted(selected) if selected else available
    for path in (TAXONOMY / "models" / f"{provider}.json" for provider in catalogued):
        catalog = json.loads(path.read_text(), parse_float=Decimal)
        provider = entries[catalog["provider"]]
        models = apply_discovery_evidence(catalog["models"], discovery_evidence(provider, TAXONOMY))
        classified += len(models)
        changed += write_catalog(path, {**catalog, "models": models})
    return ParametersDiscovered(classified, changed)
