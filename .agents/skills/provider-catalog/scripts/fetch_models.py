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
from paths import TAXONOMY

import yaml

from model_kind import text_only

ROOT = TAXONOMY
OUT = ROOT / "models"
CTX = ssl.create_default_context()
UA = "airllm-taxonomy/1.0"

# Endpoints and credential names both come from providers.yml, which is the one place
# either is written down. OPEN lists the providers whose catalog needs no credential.
OPEN = {"nvidia", "sambanova", "deepinfra", "novita", "huggingface"}



def blank(model_id: str) -> dict:
    return {
        "id": model_id,
        "context_length": None,
        "max_output_tokens": None,
        "input_modalities": None,
        "output_modalities": None,
        "supports_tools": None,
        "supports_structured_output": None,
    }




def normalize(provider: str, payload) -> list[dict]:
    items = payload.get("data") if isinstance(payload, dict) else payload
    if items is None and isinstance(payload, dict):
        items = payload.get("models") or payload.get("results")
    if not isinstance(items, list):
        return []

    out = []
    for it in items:
        if isinstance(it, str):
            out.append(blank(it))
            continue
        if not isinstance(it, dict):
            continue
        rec = blank(it.get("id") or it.get("name") or it.get("model") or "")

        if provider == "novita":
            rec["context_length"] = it.get("context_size")
            rec["max_output_tokens"] = it.get("max_output_tokens")
            rec["input_modalities"] = it.get("input_modalities")
            rec["output_modalities"] = it.get("output_modalities")
            features = it.get("features") or []
            if features:
                rec["supports_tools"] = "function-calling" in features or "tool-calling" in features
                rec["supports_structured_output"] = "structured-outputs" in features or "json-mode" in features

        elif provider == "huggingface":
            arch = it.get("architecture") or {}
            rec["input_modalities"] = arch.get("input_modalities")
            rec["output_modalities"] = arch.get("output_modalities")
            routes = [p for p in (it.get("providers") or []) if p.get("status") == "live"]
            if routes:
                rec["context_length"] = max((p.get("context_length") or 0) for p in routes) or None
                rec["supports_tools"] = any(p.get("supports_tools") for p in routes)
                rec["supports_structured_output"] = any(p.get("supports_structured_output") for p in routes)
                rec["routes"] = sorted({p.get("provider") for p in routes if p.get("provider")})

        elif provider == "deepinfra":
            meta = it.get("metadata") or {}
            tags = meta.get("tags") or []
            rec["context_length"] = meta.get("context_length")
            rec["max_output_tokens"] = meta.get("max_tokens")
            if tags:
                rec["input_modalities"] = ["text"] + (["image"] if "vision" in tags or "vlm" in tags else [])
                rec["output_modalities"] = ["image"] if "image-gen" in tags else ["audio"] if "tts" in tags else ["text"]
                rec["tags"] = tags
            pr = meta.get("pricing") or {}

        elif provider == "sambanova":
            rec["context_length"] = it.get("context_length")
            rec["max_output_tokens"] = it.get("max_completion_tokens")

        elif provider == "anthropic":
            rec["id"] = it.get("id")
            rec["display_name"] = it.get("display_name")

        elif provider == "cohere":
            rec["id"] = it.get("name")
            rec["context_length"] = it.get("context_length")
            rec["endpoints"] = it.get("endpoints") or None

        elif provider == "gemini":
            rec["id"] = (it.get("name") or "").removeprefix("models/")
            rec["display_name"] = it.get("displayName")
            rec["context_length"] = it.get("inputTokenLimit")
            rec["max_output_tokens"] = it.get("outputTokenLimit")
            rec["methods"] = it.get("supportedGenerationMethods")

        out.append(rec)
    return out


# Fields the listing endpoint never returns; they are added downstream by enrich_limits.
# Refetching must not drop them, or every refresh discards enrichment and moves the
# fetched stamp even when the vendor returned exactly what it returned last time.
DOWNSTREAM = ("kind", "limits_source", "context_length", "max_output_tokens")


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


def fetch(provider: str, url: str, env: str | None):
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if env:
        key = os.environ.get(env)
        if not key:
            return None, f"no {env} in environment"
        if provider == "anthropic":
            headers["x-api-key"] = key
            headers["anthropic-version"] = "2023-06-01"
        elif provider == "reka":
            headers["X-Api-Key"] = key
        else:
            headers["Authorization"] = f"Bearer {key}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60, context=CTX) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, type(e).__name__


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

    for provider in sorted(wanted):
        url = providers[provider]["models_url"]
        if "{" in url:
            skipped.append((provider, f"account-scoped endpoint, resolve {url}"))
            continue
        env = None if provider in OPEN else providers[provider]["env_var"]
        payload, err = fetch(provider, url, env)
        if err:
            (skipped if err.startswith("no ") else failed).append((provider, err))
            continue
        models = text_only(normalize(provider, payload))
        if not models:
            failed.append((provider, "empty or unrecognized payload"))
            continue
        declared = sum(1 for m in models if m.get("context_length") or m.get("supports_tools") is not None)
        target = OUT / f"{provider}.json"
        write_catalog(target, {
            "provider": provider, "source": url, "source_type": "api",
            "updated": stamp, "models": carry_forward(target, models),
        })
        ok.append((provider, len(models), declared))

    for p, n, d in ok:
        print(f"  ok      {p:<13} {n:>4} models, {d:>4} with declared capabilities")
    for p, why in skipped:
        print(f"  skip    {p:<13} {why}")
    for p, why in failed:
        print(f"  fail    {p:<13} {why}")
    print(f"\n{len(ok)} written, {len(skipped)} skipped, {len(failed)} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
