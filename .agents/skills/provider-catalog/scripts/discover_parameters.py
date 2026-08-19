from __future__ import annotations

import json

import yaml
from canonical import write_catalog
from parameter_support import apply_discovery_evidence, discovery_evidence
from paths import TAXONOMY


def main() -> int:
    providers = {
        provider["id"]: provider
        for filename, group in (("providers.yml", "providers"), ("routers.yml", "routers"))
        for provider in yaml.safe_load((TAXONOMY / filename).read_text())[group]
    }
    changed = 0
    classified = 0
    for path in sorted((TAXONOMY / "models").glob("*.json")):
        catalog = json.loads(path.read_text())
        provider = providers[catalog["provider"]]
        models = apply_discovery_evidence(catalog["models"], discovery_evidence(provider, TAXONOMY))
        classified += len(models)
        changed += write_catalog(path, {**catalog, "models": models})
    print(f"parameter support discovered for {classified} models; {changed} catalogs changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
