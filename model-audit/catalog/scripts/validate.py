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
from importlib.util import find_spec
from pathlib import Path

from paths import TAXONOMY

import yaml
from contract import MODALITIES

HAS_JSONSCHEMA = find_spec("jsonschema") is not None

sys.path.insert(0, str(Path(__file__).resolve().parent))
from canonical import MODEL_ORDER, sort_models
from model_kind import classify
from parameter_support import discovery_evidence

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
    "ingress",
    "primary_surface",
    "auth",
    "env_var",
    "schema",
}
PROFILE_FIELDS = {"param_aliases", "params_closed", "accepted_params"}
INGRESS = {"oai", "oai_responses", "anthropic", "google", "other_standard", "custom"}
# ingresses that carry a schema; google is the one shape we have not extracted
WIRE = {"oai", "oai_responses", "anthropic", "custom"}
AUTH_BARE = {"bearer", "sigv4", "oauth"}
PARTS = {"request", "response", "stream"}
# bare markers name a source; "alias:<model id>" names the sibling a value was inherited
# from, so an inherited number stays traceable to the record it came from
VALUE_SOURCE = {"provider", "models.dev", "openrouter-index", "vendor-docs"}


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
        if missing := FIELDS - set(e):
            fail("fields", f"{eid} is missing {sorted(missing)} from the standard field set")
        if extra := set(e) - FIELDS - PROFILE_FIELDS:
            fail("fields", f"{eid} has unknown fields {sorted(extra)}")
        if eid in seen_ids:
            fail("id", f"{eid} is declared twice")
        seen_ids.add(eid)
        if bad := set(e.get("ingress") or []) - INGRESS:
            fail("ingress", f"{eid} uses {sorted(bad)}, outside the vocabulary")
        if e.get("primary_surface") not in (e.get("ingress") or []):
            fail("ingress", f"{eid} primary_surface is not one of its ingresses")
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
                if HAS_JSONSCHEMA:
                    from jsonschema import Draft202012Validator

                    try:
                        Draft202012Validator.check_schema(doc)
                    except Exception as exc:
                        fail("schema", f"{rel} is not a valid JSON Schema: {str(exc)[:100]}")

    for f in sorted((ROOT / "schemas" / "completion").glob("*.json")):
        if f.name not in referenced:
            fail("schema", f"{f.name} is not referenced by any entry")


def check_models(all_entries: list[dict]) -> None:
    known = {entry["id"]: entry for entry in all_entries}
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
            for field in ("input_modalities", "output_modalities"):
                modalities = m.get(field)
                if not isinstance(modalities, list) or not modalities or any(not isinstance(modality, str) for modality in modalities):
                    fail("models", f"{provider}/{mid}.{field} must be a non-empty list of canonical modalities")
                    continue
                if unknown_modalities := sorted(set(modalities) - set(MODALITIES)):
                    fail("models", f"{provider}/{mid}.{field} uses unknown modalities {unknown_modalities}")
                if len(modalities) != len(set(modalities)):
                    fail("models", f"{provider}/{mid}.{field} repeats a modality")
            context_source = m.get("context_source")
            output_source = m.get("max_output_source")
            if not known_source(context_source, VALUE_SOURCE):
                fail("models", f"{provider}/{mid} has context_source {context_source!r}")
            if not known_source(output_source, VALUE_SOURCE):
                fail("models", f"{provider}/{mid} has max_output_source {output_source!r}")
            if bool(m.get("context_length")) != bool(context_source):
                fail("models", f"{provider}/{mid} must carry context_length and context_source together")
            if bool(m.get("max_output_tokens")) != bool(output_source):
                fail("models", f"{provider}/{mid} must carry max_output_tokens and max_output_source together")
            psource = m.get("pricing_source")
            if not known_source(psource, VALUE_SOURCE):
                fail("models", f"{provider}/{mid} has pricing_source {psource!r}")
            if psource and not m.get("pricing"):
                fail("models", f"{provider}/{mid} claims a pricing source but carries no price")
            if m.get("pricing") and not psource:
                fail("models", f"{provider}/{mid} has a price with no pricing_source")
            if "vendor-docs" in {context_source, output_source, psource} and not str(m.get("documentation_url", "")).startswith("https://"):
                fail("models", f"{provider}/{mid} cites vendor-docs without an HTTPS documentation_url")
            if m.get("source_conflicts") and not str(m.get("documentation_url", "")).startswith("https://"):
                fail("models", f"{provider}/{mid} records a source conflict without an HTTPS documentation_url")
            evidence = m.get("parameter_evidence") or {}
            if extra_sources := set(evidence) - {"model_discovery"}:
                fail("models", f"{provider}/{mid} has unknown parameter evidence {sorted(extra_sources)}")
            if evidence.get("model_discovery") != expected_discovery:
                fail("models", f"{provider}/{mid} has stale or missing model-discovery parameter evidence; run discover_parameters.py")
            if not evidence.get("model_discovery", {}).get("sources"):
                fail("models", f"{provider}/{mid} has model-discovery parameter evidence without a request schema")


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
    from model_audit.taxonomy import write

    _, _, changed = write(ROOT.parent, check=True)
    if changed:
        fail("applied", "taxonomy.yml is out of date; run airllm-audit taxonomy build")


def check_seed(all_entries: list[dict]) -> None:
    """The seed must stay a faithful projection of the catalog, or a rebuild loses data."""
    seed_path = Path(__file__).resolve().parent.parent / "seed.yml"
    if not seed_path.exists():
        fail("seed", "seed.yml is missing; a rebuild from scratch would be impossible")
        return
    carried = ("id", "name", "icon_mono", "icon_color", "homepage", "docs", "base_url", "openapi", "models_url", "ingress", "auth", "env_var")
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

    if not HAS_JSONSCHEMA:
        print("note: jsonschema is not installed, so schemas were not compiled")

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
