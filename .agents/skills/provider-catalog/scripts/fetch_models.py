"""Fetch provider model catalogs and normalize them into taxonomy/models."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canonical import write_catalog
from capability_support import apply_discovery_evidence as apply_capability_discovery_evidence
from capability_support import discovery_evidence as capability_discovery_evidence
from evidence import CAPABILITY_PROBE_VERSION, PARAMETER_PROBE_VERSION, current_targets, live_evidence_is_current
from model_kind import text_only
from parameter_support import apply_discovery_evidence, discovery_evidence
from paths import ENV_FILE, TAXONOMY
from provider_profile import catalog_headers, endpoints, select_provider_ids
from sources import registry

ROOT = TAXONOMY
OUT = ROOT / "models"


def _secondary_source(value: object) -> bool:
    return isinstance(value, str) and value != "provider"


def _current_live_probe(provider: dict, model: dict, previous: dict, field: str, suite: str, version: int) -> dict | None:
    evidence = previous.get(field) or {}
    live_probe = evidence.get("live_probe") or {}
    targets = current_targets(provider, model, endpoints(provider), suite, version)
    return live_probe if live_evidence_is_current(live_probe, targets, version) else None


def carry_forward(path: Path, models: list[dict], provider: dict | None = None) -> list[dict]:
    if not path.exists():
        return models
    try:
        previous = {model["id"]: model for model in json.loads(path.read_text()).get("models") or []}
    except (json.JSONDecodeError, KeyError):
        return models
    for model in models:
        old = previous.get(model.get("id"))
        if not old:
            continue
        if _secondary_source(old.get("limits_source")):
            for field in ("context_length", "max_output_tokens", "limits_source"):
                if model.get(field) in (None, [], {}) and old.get(field) is not None:
                    model[field] = old[field]
        if _secondary_source(old.get("pricing_source")):
            for field in ("pricing", "pricing_source"):
                if model.get(field) in (None, [], {}) and old.get(field) is not None:
                    model[field] = old[field]
        if provider is not None:
            parameter_probe = _current_live_probe(provider, model, old, "parameter_evidence", "parameters", PARAMETER_PROBE_VERSION)
            capability_probe = _current_live_probe(provider, model, old, "capability_evidence", "capabilities", CAPABILITY_PROBE_VERSION)
            if parameter_probe:
                model["parameter_evidence"] = {"live_probe": parameter_probe}
            if capability_probe:
                model["capability_evidence"] = {"live_probe": capability_probe}
    return models


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch provider model catalogs")
    parser.add_argument("providers", nargs="*", help="Provider ids; defaults to every active provider")
    parser.add_argument("--allow-missing-credentials", action="store_true")
    return parser.parse_args(argv)


def _http_error(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return f"HTTP {exc.code}"
    error = payload.get("error") if isinstance(payload, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return f"HTTP {exc.code}" + (f": {message[:110]}" if isinstance(message, str) else "")


def main() -> int:
    arguments = parse_args()
    load_dotenv(ENV_FILE)
    providers = {provider["id"]: provider for provider in yaml.safe_load((ROOT / "providers.yml").read_text())["providers"]}
    try:
        wanted = select_provider_ids(set(arguments.providers), set(providers))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    OUT.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    ok: list[tuple[str, int, int, int]] = []
    skipped: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []
    sources = registry()
    for provider_id in sorted(wanted):
        provider = providers[provider_id]
        source = sources.get(provider_id)
        if source is None:
            failed.append((provider_id, "no module under sources/; add one to fetch it"))
            continue
        url = provider["models_url"]
        if "{" in url:
            failed.append((provider_id, f"unresolved model-catalog URL {url}"))
            continue
        env_var = provider["env_var"]
        key = os.environ.get(env_var)
        if provider["models_auth"] != "none" and not key:
            target = skipped if arguments.allow_missing_credentials else failed
            target.append((provider_id, f"no {env_var} in environment"))
            continue
        try:
            payload = source.fetch(url, catalog_headers(provider, key))
        except urllib.error.HTTPError as exc:
            failed.append((provider_id, _http_error(exc)))
            continue
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            failed.append((provider_id, type(exc).__name__))
            continue
        raw = source.items(payload)
        models = text_only([model for model in (source.normalize(item) for item in raw) if model])
        if raw and not models:
            failed.append((provider_id, f"{len(raw)} returned, none kept; check the module's filter"))
            continue
        if not models:
            failed.append((provider_id, "empty or unrecognized payload"))
            continue
        declared = sum(1 for model in models if model.get("context_length") or model.get("supports_tools") is not None)
        path = OUT / f"{provider_id}.json"
        previous_ids = {model["id"] for model in json.loads(path.read_text()).get("models") or []} if path.exists() else set()
        models = carry_forward(path, models, provider)
        models = apply_discovery_evidence(models, discovery_evidence(provider, ROOT))
        models = apply_capability_discovery_evidence(models, capability_discovery_evidence(provider))
        write_catalog(
            path,
            {"provider": provider_id, "source": url, "source_type": "api", "updated": stamp, "models": models},
        )
        ok.append((provider_id, len(models), declared, len([model for model in models if model["id"] not in previous_ids])))

    for provider_id, model_count, declared, new in ok:
        print(f"  ok      {provider_id:<13} {model_count:>4} models, {declared:>4} declared, {new:>3} new")
    for provider_id, reason in skipped:
        print(f"  skip    {provider_id:<13} {reason}")
    for provider_id, reason in failed:
        print(f"  fail    {provider_id:<13} {reason}")
    print(f"\n{len(ok)} written, {len(skipped)} skipped, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
