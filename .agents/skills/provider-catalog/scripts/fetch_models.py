"""Fetch each provider's model catalog and normalize it into taxonomy/models.

Reads providers.yml, calls every provider's model listing endpoint with whatever
credential is in the environment, and writes one file per provider. Providers whose key
is absent are skipped and reported, so a partial run is legible rather than silently thin.

    uv run python taxonomy/fetch_models.py [provider_id ...]

Capability fields are populated only where the provider itself declares them. A null means
the provider does not say, never that the capability is absent: most catalogs return bare
model ids, and inferring tool support from a name would be invention.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canonical import write_catalog, write_schema
from parameter_support import apply_discovery_evidence, discovery_evidence
from paths import TAXONOMY
from probe_parameters import probe_models

import yaml

from model_kind import text_only
from sources import registry

ROOT = TAXONOMY
OUT = ROOT / "models"
CTX = ssl.create_default_context()
UA = "airllm-taxonomy/1.0"








# Fields the listing endpoint never returns; they are added downstream by enrich_limits.
# Refetching must not drop them, or every refresh discards enrichment and moves the
# fetched stamp even when the vendor returned exactly what it returned last time.
# provenance travels with the value it describes. Carrying "pricing" without
# "pricing_source" lets the next enrichment restamp a borrowed price as provider-supplied
# endpoint_status is written by smoke.py per endpoint and decides a model's egress_kind, so
# dropping it here would silently demote every proven Responses model on the next refresh
DOWNSTREAM = ("kind", "limits_source", "pricing_source", "context_length", "max_output_tokens", "pricing",
              "reachable", "reachable_checked", "endpoint_status", "parameter_evidence")


def carry_forward(path: Path, models: list[dict]) -> list[dict]:
    if not path.exists():
        return models
    try:
        previous = {m["id"]: m for m in json.loads(path.read_text()).get("models") or []}
    except (json.JSONDecodeError, KeyError):
        return models
    for model in models:
        old = previous.get(model.get("id"))
        if not old:
            continue
        for field in DOWNSTREAM:
            if model.get(field) in (None, [], {}) and old.get(field) is not None:
                model[field] = old[field]
    return models




def main() -> int:
    providers = {p["id"]: p for p in yaml.safe_load((ROOT / "providers.yml").read_text())["providers"]}
    wanted = set(sys.argv[1:]) or set(providers)
    unknown = wanted - set(providers)
    if unknown:
        print(f"not in providers.yml: {sorted(unknown)}")
        return 2

    OUT.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ok, skipped, failed = [], [], []

    sources = registry()
    for provider in sorted(wanted):
        source = sources.get(provider)
        if source is None:
            skipped.append((provider, "no module under sources/; add one to fetch it"))
            continue
        url = providers[provider]["models_url"]
        if "{" in url:
            skipped.append((provider, f"account-scoped endpoint, resolve {url}"))
            continue
        key = None
        if not source.open_access:
            env = providers[provider]["env_var"]
            key = os.environ.get(env)
            if not key:
                skipped.append((provider, f"no {env} in environment"))
                continue
        try:
            payload = source.fetch(key)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = ": " + (json.loads(exc.read().decode()).get("error") or {}).get("message", "")[:110]
            except Exception:
                pass
            failed.append((provider, f"HTTP {exc.code}{detail}"))
            continue
        except Exception as exc:
            failed.append((provider, type(exc).__name__))
            continue
        raw = source.items(payload)
        models = text_only([m for m in (source.normalize(i) for i in raw) if m])
        if raw and not models:
            failed.append((provider, f"{len(raw)} returned, none kept; check the module's filter"))
            continue
        if not models:
            failed.append((provider, "empty or unrecognized payload"))
            continue
        declared = sum(1 for m in models if m.get("context_length") or m.get("supports_tools") is not None)
        target = OUT / f"{provider}.json"
        previous_ids = {model["id"] for model in json.loads(target.read_text()).get("models") or []} if target.exists() else set()
        models = carry_forward(target, models)
        models = apply_discovery_evidence(models, discovery_evidence(providers[provider], ROOT))
        new_models = [model for model in models if model["id"] not in previous_ids]
        attempted, conclusive = probe_models(providers[provider], new_models, key) if key else (0, 0)
        write_catalog(target, {
            "provider": provider, "source": source.url, "source_type": "api",
            "updated": stamp, "models": models,
        })
        ok.append((provider, len(models), declared, len(new_models), attempted, conclusive))

    for p, n, d, new, attempted, conclusive in ok:
        print(f"  ok      {p:<13} {n:>4} models, {d:>4} declared, {new:>3} new, {conclusive:>3}/{attempted:<3} probes conclusive")
    for p, why in skipped:
        print(f"  skip    {p:<13} {why}")
    for p, why in failed:
        print(f"  fail    {p:<13} {why}")
    print(f"\n{len(ok)} written, {len(skipped)} skipped, {len(failed)} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
