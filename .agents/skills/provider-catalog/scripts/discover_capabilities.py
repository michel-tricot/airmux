from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from canonical import write_catalog
from capability_support import apply_discovery_evidence, discovery_evidence
from paths import TAXONOMY


def main() -> int:
    providers = {provider["id"]: provider for provider in yaml.safe_load((TAXONOMY / "providers.yml").read_text())["providers"]}
    changed = 0
    models = 0
    for path in sorted((TAXONOMY / "models").glob("*.json")):
        catalog = json.loads(path.read_text())
        provider = providers.get(catalog["provider"])
        if provider is None:
            continue
        apply_discovery_evidence(catalog["models"], discovery_evidence(provider))
        models += len(catalog["models"])
        changed += write_catalog(path, catalog)
    print(f"capability discovery refreshed for {models} models; {changed} catalogs changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
