from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from canonical import write_catalog
from parameter_support import ENDPOINTS, SUPPORT
from paths import TAXONOMY

CLAIMS = Path(__file__).resolve().parent.parent / "parameter-docs.yml"


def evidence_by_model(claims: list[dict]) -> dict[tuple[str, str], dict]:
    evidence: dict[tuple[str, str], dict] = {}
    for claim in claims:
        bad_endpoints = set(claim["endpoints"]) - ENDPOINTS
        bad_statuses = set(claim["parameters"].values()) - SUPPORT
        if bad_endpoints or bad_statuses:
            raise ValueError(f"invalid parameter claim for {claim['provider']}: endpoints={bad_endpoints}, statuses={bad_statuses}")
        for model_id in claim["models"]:
            model_evidence = evidence.setdefault((claim["provider"], model_id), {"sources": [], "support": {}})
            if claim["source"] not in model_evidence["sources"]:
                model_evidence["sources"].append(claim["source"])
            for endpoint in claim["endpoints"]:
                support = model_evidence["support"].setdefault(endpoint, {})
                for parameter, status in claim["parameters"].items():
                    previous = support.get(parameter)
                    if previous is not None and previous != status:
                        raise ValueError(f"conflicting documentation for {claim['provider']}/{model_id}/{endpoint}/{parameter}")
                    support[parameter] = status
    return evidence


def main() -> int:
    documented = evidence_by_model(yaml.safe_load(CLAIMS.read_text())["claims"])
    changed = 0
    for path in sorted((TAXONOMY / "models").glob("*.json")):
        catalog = json.loads(path.read_text())
        provider = catalog["provider"]
        for model in catalog["models"]:
            parameter_evidence = dict(model.get("parameter_evidence") or {})
            vendor_docs = documented.get((provider, model["id"]))
            if vendor_docs is None:
                parameter_evidence.pop("vendor_docs", None)
            else:
                parameter_evidence["vendor_docs"] = vendor_docs
            if parameter_evidence:
                model["parameter_evidence"] = parameter_evidence
            else:
                model.pop("parameter_evidence", None)
        changed += write_catalog(path, catalog)
    print(f"parameter documentation applied to {len(documented)} models; {changed} catalogs changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
