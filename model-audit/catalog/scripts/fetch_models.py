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

import contextlib
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml
from canonical import write_catalog
from model_kind import text_only
from parameter_support import apply_discovery_evidence, discovery_evidence
from paths import TAXONOMY
from sources import registry
from sources.base import GenericModelSource

from model_audit.catalog_ops import incomplete_model_modalities, retain_documented_models

ROOT = TAXONOMY
OUT = ROOT / "models"
CTX = ssl.create_default_context()
UA = "tokkeeper-taxonomy/1.0"


def main() -> int:
    providers = {p["id"]: p for p in yaml.safe_load((ROOT / "providers.yml").read_text())["providers"]}
    wanted = set(sys.argv[1:]) or set(providers)
    unknown = wanted - set(providers)
    if unknown:
        print(f"not in providers.yml: {sorted(unknown)}")
        return 2

    OUT.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    ok, skipped, failed = [], [], []

    sources = registry()
    for provider in sorted(wanted):
        source = sources.get(provider)
        if source is None:
            source = GenericModelSource()
            source.id = provider
            source.url = providers[provider]["models_url"]
            auth = (providers[provider].get("auth") or ["bearer"])[0]
            source.auth = f"header:{auth.split(':', 1)[1]}" if auth.startswith("header_key:") else auth
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
            raw = source.items(payload)
            models = text_only(source.enrich([model for model in (source.normalize(item) for item in raw) if model]))
        except urllib.error.HTTPError as exc:
            detail = ""
            with contextlib.suppress(UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                detail = ": " + (json.loads(exc.read().decode()).get("error") or {}).get("message", "")[:110]
            failed.append((provider, f"HTTP {exc.code}{detail}"))
            continue
        except Exception as exc:
            failed.append((provider, f"{type(exc).__name__}: {str(exc)[:110]}"))
            continue
        if raw and not models:
            failed.append((provider, f"{len(raw)} returned, none kept; check the module's filter"))
            continue
        if not models:
            failed.append((provider, "empty or unrecognized payload"))
            continue
        if incomplete := incomplete_model_modalities(provider, models):
            failed.append((provider, f"models without required modalities: {', '.join(incomplete)}"))
            continue
        target = OUT / f"{provider}.json"
        previous_models = json.loads(target.read_text()).get("models") or [] if target.exists() else []
        previous_ids = {model["id"] for model in previous_models}
        models = apply_discovery_evidence(models, discovery_evidence(providers[provider], ROOT))
        models = retain_documented_models(models, previous_models)
        declared = sum(1 for model in models if model.get("context_length") or model.get("supports_tools") is not None)
        new_models = [model for model in models if model["id"] not in previous_ids]
        write_catalog(
            target,
            {
                "provider": provider,
                "source": source.url,
                "source_type": "api",
                "updated": stamp,
                "models": models,
            },
        )
        ok.append((provider, len(models), declared, len(new_models)))

    for p, n, d, new in ok:
        print(f"  ok      {p:<13} {n:>4} models, {d:>4} declared, {new:>3} new")
    for p, why in skipped:
        print(f"  skip    {p:<13} {why}")
    for p, why in failed:
        print(f"  fail    {p:<13} {why}")
    print(f"\n{len(ok)} written, {len(skipped)} skipped, {len(failed)} failed")
    return 1 if failed or (set(sys.argv[1:]) and skipped) else 0


if __name__ == "__main__":
    raise SystemExit(main())
