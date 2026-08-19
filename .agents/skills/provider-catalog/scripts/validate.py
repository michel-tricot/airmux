"""Structural gates for the provider catalog.

Everything here was a check run by hand while the catalog was built. Collected into one
place so drift fails loudly instead of being noticed by whoever reads the file next.

    uv run python taxonomy/validate.py

Exits non-zero on the first category with failures. Each failure names the entry and the
rule, so the fix is obvious without reading this file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from paths import TAXONOMY

sys.path.insert(0, str(Path(__file__).resolve().parent))
from canonical import MODEL_ORDER, sort_models
from capability_support import PROBES
from capability_support import SUPPORT as CAPABILITY_SUPPORT
from capability_support import discovery_evidence as capability_discovery_evidence
from evidence import (
    CAPABILITY_PROBE_VERSION,
    PARAMETER_PROBE_VERSION,
    REACHABILITY_PROBE_VERSION,
    current_targets,
    live_evidence_is_current,
    target_fingerprint,
)
from model_kind import classify
from parameter_support import ENDPOINTS, INGRESS_ENDPOINT, PARAMETERS, SUPPORT, discovery_evidence
from probe_parameters import PROBES as PARAMETER_PROBES
from provider_profile import catalog_headers, endpoints, provider_surfaces

ROOT = TAXONOMY
FIELDS = {
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
}
INGRESS = {"oai", "oai_responses", "anthropic", "google", "other_standard", "custom"}
# ingresses that carry a schema; google is the one shape we have not extracted
WIRE = {"oai", "oai_responses", "anthropic", "custom"}
AUTH_BARE = {"bearer", "sigv4", "oauth"}
PARTS = {"request", "response", "stream"}
# bare markers name a source; "alias:<model id>" names the sibling a value was inherited
# from, so an inherited number stays traceable to the record it came from
LIMITS_SOURCE = {"provider", "models.dev", "openrouter-index", "vendor-docs"}
PRICING_SOURCE = LIMITS_SOURCE


def known_source(value: str | None, vocabulary: set[str]) -> bool:
    if value is None or value in vocabulary:
        return True
    return value.startswith("alias:") and len(value.split(":", 1)[1]) > 1


ROOT_FORMS = {"properties", "$ref", "oneOf", "anyOf", "allOf", "type", "items"}

# A wire ingress with no schema is normally a hole. These are the exceptions, recorded
# with the reason so the gap stays visible instead of being quietly tolerated.
KNOWN_GAPS = {
    ("bedrock", "custom"): "AWS publishes a Smithy service model for Converse, not OpenAPI",
}

failures: list[str] = []


def fail(rule: str, detail: str) -> None:
    failures.append(f"{rule}: {detail}")


def entries() -> list[dict]:
    out = []
    for filename, key in (("providers.yml", "providers"), ("routers.yml", "routers")):
        path = ROOT / filename
        if path.exists():
            out += yaml.safe_load(path.read_text())[key]
    return out


def check_shape(all_entries: list[dict]) -> None:
    seen_ids, seen_env = set(), {}
    for e in all_entries:
        eid = e.get("id", "<unnamed>")
        if set(e) != FIELDS:
            fail("fields", f"{eid} has {sorted(set(e) ^ FIELDS)} differing from the standard field set")
        if eid in seen_ids:
            fail("id", f"{eid} is declared twice")
        seen_ids.add(eid)
        if bad := set(e.get("ingress") or []) - INGRESS:
            fail("ingress", f"{eid} uses {sorted(bad)}, outside the vocabulary")
        for value in e.get("auth") or []:
            if value not in AUTH_BARE and not value.startswith("header_key:"):
                fail("auth", f"{eid} uses {value}, outside the vocabulary")
            if value.startswith("header_key:") and len(value.split(":", 1)[1]) < 2:
                fail("auth", f"{eid} declares header_key with no header name")
        env = e.get("env_var")
        if not env:
            fail("env_var", f"{eid} has no credential variable")
        elif env in seen_env and seen_env[env] != eid:
            fail("env_var", f"{env} is claimed by both {seen_env[env]} and {eid}")
        else:
            seen_env[env] = eid
        if not (e.get("models_url") or "").startswith("http"):
            fail("models_url", f"{eid} has no usable listing endpoint")
        if not (e.get("base_url") or "").startswith("http"):
            fail("base_url", f"{eid} has no inference endpoint; the applied taxonomy needs one")
        try:
            provider_surfaces(e)
            catalog_headers(e, "validation-key")
        except ValueError as exc:
            fail("surface", str(exc))


def check_icons(all_entries: list[dict]) -> None:
    available = {f.stem for f in (ROOT / "icons").glob("*.svg")}
    referenced = set()
    for e in all_entries:
        for field in ("icon_mono", "icon_color"):
            slug = e.get(field)
            if not slug:
                fail("icon", f"{e['id']} has no {field}; both variants are required")
                continue
            referenced.add(slug)
            if slug not in available:
                fail("icon", f"{e['id']}.{field} references {slug}.svg, which is not in taxonomy/icons")
    for orphan in sorted(available - referenced):
        fail("icon", f"{orphan}.svg is not referenced by any entry")


def check_schemas(all_entries: list[dict]) -> None:
    referenced: set[str] = set()
    for e in all_entries:
        eid, schema = e["id"], e.get("schema")
        wire = {i for i in e.get("ingress") or [] if i in WIRE}
        if not wire:
            if schema is not None:
                fail("schema", f"{eid} declares schemas but no wire-standard ingress")
            continue
        if not schema:
            fail("schema", f"{eid} serves {sorted(wire)} but carries no schema")
            continue
        if set(schema) != {"completion"}:
            fail("schema", f"{eid} has kinds {sorted(schema)}; only completion exists today")
            continue
        if extra := set(schema["completion"]) - wire:
            fail("schema", f"{eid} has schemas for {sorted(extra)}, which it does not declare as ingress")
        for ingress in sorted(wire - set(schema["completion"])):
            if (eid, ingress) not in KNOWN_GAPS:
                fail("schema", f"{eid} serves {ingress} but has no schema for it")
        for ingress, parts in schema["completion"].items():
            if bad := set(parts) - PARTS:
                fail("schema", f"{eid}/{ingress} has unknown parts {sorted(bad)}")
            if "request" not in parts:
                fail("schema", f"{eid}/{ingress} has no request schema")
            for part, rel in parts.items():
                referenced.add(Path(rel).name)
                path = ROOT / rel
                if not path.exists():
                    fail("schema", f"{eid}/{ingress}/{part} points at {rel}, which does not exist")
                    continue
                if not Path(rel).name.startswith(f"{ingress}."):
                    fail("schema", f"{rel} does not start with its ingress {ingress}")
                if not Path(rel).name.endswith(f".{part}.json"):
                    fail("schema", f"{rel} does not end with its part {part}")
                try:
                    doc = json.loads(path.read_text())
                except json.JSONDecodeError as exc:
                    fail("schema", f"{rel} is not valid JSON: {exc}")
                    continue
                if not (ROOT_FORMS & set(doc)):
                    fail("schema", f"{rel} has no root schema form, so it constrains nothing")
                try:
                    Draft202012Validator.check_schema(doc)
                except SchemaError as exc:
                    fail("schema", f"{rel} is not a valid JSON Schema: {str(exc)[:100]}")

    for f in sorted((ROOT / "schemas" / "completion").glob("*.json")):
        if f.name not in referenced:
            fail("schema", f"{f.name} is not referenced by any entry")


def check_models(all_entries: list[dict]) -> None:
    known = {entry["id"]: entry for entry in all_entries}
    active_providers = {provider["id"] for provider in yaml.safe_load((ROOT / "providers.yml").read_text())["providers"]}
    catalog_ids = {path.stem for path in (ROOT / "models").glob("*.json")}
    for provider in sorted(active_providers - catalog_ids):
        fail("models", f"{provider} has no model catalog")
    for f in sorted((ROOT / "models").glob("*.json")):
        doc = json.loads(f.read_text())
        provider = doc.get("provider")
        if provider not in known:
            fail("models", f"{f.name} is for {provider}, which is in neither catalog")
        if doc.get("source_type") not in {"api", "docs"}:
            fail("models", f"{provider} has source_type {doc.get('source_type')!r}")
        if doc.get("count") != len(doc.get("models") or []):
            fail("models", f"{provider} count {doc.get('count')} disagrees with {len(doc.get('models') or [])} entries")
        models = doc.get("models") or []
        if [m.get("id") for m in models] != [m.get("id") for m in sort_models([dict(m) for m in models])]:
            fail("models", f"{provider} is not sorted by id; regenerate so diffs stay reviewable")
        expected_discovery = discovery_evidence(known[provider], ROOT) if provider in known else None
        expected_capability_discovery = capability_discovery_evidence(known[provider]) if provider in known else None
        for m in models:
            leading = [k for k in m if k in MODEL_ORDER]
            if leading != [k for k in MODEL_ORDER if k in m]:
                fail("models", f"{provider}/{m.get('id')} has non-canonical key order")
                break
        seen = set()
        for m in models:
            mid = m.get("id")
            if not mid:
                fail("models", f"{provider} has a model with no id")
                continue
            if mid in seen:
                fail("models", f"{provider} lists {mid} twice")
            seen.add(mid)
            if (kind := classify(mid, m)) != "text":
                fail("models", f"{provider}/{mid} classifies as {kind}; the catalog is text-only")
            source = m.get("limits_source")
            if not known_source(source, LIMITS_SOURCE):
                fail("models", f"{provider}/{mid} has limits_source {source!r}")
            if source in LIMITS_SOURCE and not (m.get("context_length") and m.get("max_output_tokens")):
                fail("models", f"{provider}/{mid} claims {source} but is missing a limit")
            psource = m.get("pricing_source")
            if not known_source(psource, PRICING_SOURCE):
                fail("models", f"{provider}/{mid} has pricing_source {psource!r}")
            if psource and not m.get("pricing"):
                fail("models", f"{provider}/{mid} claims a pricing source but carries no price")
            if m.get("pricing") and not psource:
                fail("models", f"{provider}/{mid} has a price with no pricing_source")
            evidence = m.get("parameter_evidence") or {}
            if extra_sources := set(evidence) - {"model_discovery", "live_probe"}:
                fail("models", f"{provider}/{mid} has unknown parameter evidence {sorted(extra_sources)}")
            if evidence.get("model_discovery") != expected_discovery:
                fail("models", f"{provider}/{mid} has stale or missing model-discovery parameter evidence; run discover_parameters.py")
            for source_type, source_evidence in evidence.items():
                if source_type == "model_discovery" and not source_evidence.get("sources"):
                    fail("models", f"{provider}/{mid} has model-discovery parameter evidence without a request schema")
                if source_type == "live_probe":
                    if extra_fields := set(source_evidence) - {"version", "targets", "attempted", "support"}:
                        fail("models", f"{provider}/{mid} has unknown live-probe fields {sorted(extra_fields)}")
                    targets = current_targets(known[provider], m, endpoints(known[provider]), "parameters", PARAMETER_PROBE_VERSION)
                    if not live_evidence_is_current(source_evidence, targets, PARAMETER_PROBE_VERSION):
                        fail("models", f"{provider}/{mid} has stale parameter probe evidence; run probe_parameters.py --replace")
                    attempted = source_evidence.get("attempted") or {}
                    if not attempted:
                        fail("models", f"{provider}/{mid} has live-probe evidence without attempted parameters")
                    if bad_endpoints := set(attempted) - ENDPOINTS:
                        fail("models", f"{provider}/{mid} has live-probe attempts for {sorted(bad_endpoints)}")
                    for endpoint, parameters in attempted.items():
                        if bad_parameters := set(parameters) - PARAMETERS:
                            fail("models", f"{provider}/{mid}/{endpoint} attempted unknown parameters {sorted(bad_parameters)}")
                support = source_evidence.get("support") or {}
                if bad_endpoints := set(support) - ENDPOINTS:
                    fail("models", f"{provider}/{mid} has parameter evidence for {sorted(bad_endpoints)}")
                for endpoint, parameters in support.items():
                    if bad_statuses := set(parameters.values()) - SUPPORT:
                        fail("models", f"{provider}/{mid}/{endpoint} has parameter statuses {sorted(bad_statuses)}")
                    if source_type == "live_probe":
                        missing_attempts = set(parameters) - set((source_evidence.get("attempted") or {}).get(endpoint) or [])
                        if missing_attempts:
                            fail("models", f"{provider}/{mid}/{endpoint} has unattempted live results {sorted(missing_attempts)}")
            capability_evidence = m.get("capability_evidence") or {}
            if extra_sources := set(capability_evidence) - {"model_discovery", "live_probe"}:
                fail("models", f"{provider}/{mid} has unknown capability evidence {sorted(extra_sources)}")
            if capability_evidence.get("model_discovery") != expected_capability_discovery:
                fail("models", f"{provider}/{mid} has stale or missing capability discovery evidence; run discover_capabilities.py")
            capability_probe = capability_evidence.get("live_probe") or {}
            if extra_fields := set(capability_probe) - {"version", "targets", "attempted", "support"}:
                fail("models", f"{provider}/{mid} has unknown live capability fields {sorted(extra_fields)}")
            capability_targets = current_targets(known[provider], m, endpoints(known[provider]), "capabilities", CAPABILITY_PROBE_VERSION)
            if not live_evidence_is_current(capability_probe, capability_targets, CAPABILITY_PROBE_VERSION):
                fail("models", f"{provider}/{mid} has stale capability evidence; run probe_capabilities.py --replace")
            capability_attempts = capability_probe.get("attempted") or {}
            capability_support = capability_probe.get("support") or {}
            if bad_endpoints := set(capability_attempts) - ENDPOINTS:
                fail("models", f"{provider}/{mid} has capability attempts for {sorted(bad_endpoints)}")
            if bad_endpoints := set(capability_support) - ENDPOINTS:
                fail("models", f"{provider}/{mid} has capability evidence for {sorted(bad_endpoints)}")
            for endpoint, probe_names in capability_attempts.items():
                if unknown := set(probe_names) - PROBES:
                    fail("models", f"{provider}/{mid}/{endpoint} attempted unknown capability probes {sorted(unknown)}")
            for endpoint, statuses in capability_support.items():
                if unknown := set(statuses) - PROBES:
                    fail("models", f"{provider}/{mid}/{endpoint} has unknown capability probes {sorted(unknown)}")
                if bad_statuses := set(statuses.values()) - CAPABILITY_SUPPORT:
                    fail("models", f"{provider}/{mid}/{endpoint} has capability statuses {sorted(bad_statuses)}")
                if missing_attempts := set(statuses) - set(capability_attempts.get(endpoint) or []):
                    fail("models", f"{provider}/{mid}/{endpoint} has unattempted capability results {sorted(missing_attempts)}")
            expected_endpoints = {INGRESS_ENDPOINT[ingress] for ingress in known[provider]["ingress"] if ingress in INGRESS_ENDPOINT}
            for endpoint in sorted(expected_endpoints):
                parameter_probe = evidence.get("live_probe") or {}
                if missing := set(PARAMETER_PROBES[endpoint]) - set((parameter_probe.get("attempted") or {}).get(endpoint) or []):
                    fail("models", f"{provider}/{mid}/{endpoint} has never attempted parameters {sorted(missing)}; run probe_parameters.py")
                if missing := PROBES - set(capability_attempts.get(endpoint) or []):
                    fail("models", f"{provider}/{mid}/{endpoint} has never attempted probes {sorted(missing)}; run probe_capabilities.py")
                endpoint_status = (m.get("endpoint_status") or {}).get(endpoint) or {}
                expected_target = target_fingerprint(known[provider], m, endpoint, "reachability", REACHABILITY_PROBE_VERSION)
                if endpoint_status.get("version") != REACHABILITY_PROBE_VERSION or endpoint_status.get("target") != expected_target:
                    fail("models", f"{provider}/{mid}/{endpoint} has stale reachability evidence; run smoke.py")


CANDIDATE_FIELDS = {"id", "name", "homepage", "docs", "env_var"}


def check_candidates(all_entries: list[dict]) -> None:
    """Candidates are tracked, not modelled. Identity only, and never derived data."""
    path = ROOT / "candidates.yml"
    if not path.exists():
        return
    active = {e["id"] for e in all_entries}
    for entry in yaml.safe_load(path.read_text())["candidates"]:
        eid = entry.get("id", "<unnamed>")
        if set(entry) != CANDIDATE_FIELDS:
            fail("candidate", f"{eid} has {sorted(set(entry) ^ CANDIDATE_FIELDS)}; candidates are identity only")
        if eid in active:
            fail("candidate", f"{eid} is both active and a candidate")
        if (ROOT / "models" / f"{eid}.json").exists():
            fail("candidate", f"{eid} still has a model catalog; candidates carry no derived data")


def check_applied() -> None:
    """taxonomy.yml is generated. If it has drifted, the database gets stale routing."""
    import subprocess

    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "build_taxonomy.py"), "--check"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail("applied", "taxonomy.yml is out of date; run build_taxonomy.py")


def check_seed(all_entries: list[dict]) -> None:
    """The seed must stay a faithful projection of the catalog, or a rebuild loses data."""
    seed_path = Path(__file__).resolve().parent.parent / "seed.yml"
    if not seed_path.exists():
        fail("seed", "seed.yml is missing; a rebuild from scratch would be impossible")
        return
    carried = (
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
    )
    seed = yaml.safe_load(seed_path.read_text())
    # candidates live in the seed too, but they are not catalog entries
    seeded = {e["id"]: e for key, group in seed.items() if key != "candidates" for e in group}
    for e in all_entries:
        if e["id"] not in seeded:
            fail("seed", f"{e['id']} is in the catalog but not the seed; run make_seed.py")
            continue
        for field in carried:
            if seeded[e["id"]].get(field) != e.get(field):
                fail("seed", f"{e['id']}.{field} differs between seed and catalog; run make_seed.py")
    for extra in sorted(set(seeded) - {e["id"] for e in all_entries}):
        fail("seed", f"{extra} is in the seed but not the catalog")


def main() -> int:
    all_entries = entries()
    check_shape(all_entries)
    check_icons(all_entries)
    check_schemas(all_entries)
    check_models(all_entries)
    check_candidates(all_entries)
    check_applied()
    check_seed(all_entries)

    if failures:
        print(f"{len(failures)} problems\n")
        for line in failures:
            print(f"  {line}")
        return 1

    models = [m for f in (ROOT / "models").glob("*.json") for m in json.loads(f.read_text())["models"]]
    complete = sum(1 for m in models if m.get("context_length") and m.get("max_output_tokens"))
    print(
        f"ok: {len(all_entries)} entries, "
        f"{len(list((ROOT / 'schemas' / 'completion').glob('*.json')))} schemas, "
        f"{len(list((ROOT / 'icons').glob('*.svg')))} icons, "
        f"{len(models)} models ({complete} with both limits)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
