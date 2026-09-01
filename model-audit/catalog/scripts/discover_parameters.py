from __future__ import annotations

import json
import sys

from canonical import write_catalog
from parameter_support import apply_discovery_evidence, discovery_evidence
from paths import TAXONOMY

from model_audit.catalog_ops import load_provider_entries


def main() -> int:
    providers = load_provider_entries(TAXONOMY)
    changed = 0
    classified = 0
    available = sorted(path.stem for path in (TAXONOMY / "models").glob("*.json"))
    selected = set(sys.argv[1:])
    unknown = selected - set(available)
    if unknown:
        print(f"not in taxonomy/models: {sorted(unknown)}")
        return 2
    catalogued = sorted(selected) if selected else available
    for path in (TAXONOMY / "models" / f"{provider}.json" for provider in catalogued):
        catalog = json.loads(path.read_text())
        provider = providers[catalog["provider"]]
        models = apply_discovery_evidence(catalog["models"], discovery_evidence(provider, TAXONOMY))
        classified += len(models)
        changed += write_catalog(path, {**catalog, "models": models})
    print(f"parameter support discovered for {classified} models; {changed} catalogs changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
