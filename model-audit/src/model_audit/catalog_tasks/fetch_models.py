"""Fetch each provider's model catalog and normalize it into taxonomy/models.

Reads providers.yml, calls every provider's model listing endpoint with whatever
credential is in the environment, and writes one file per provider. Providers whose key
is absent are skipped and reported, so a partial run is legible rather than silently thin.

    uv run airmux-audit providers sync [provider_id] --only models

Capability fields are populated only where the provider itself declares them. A null means
the provider does not say, never that the capability is absent: most catalogs return bare
model ids, and inferring tool support from a name would be invention.
"""

from __future__ import annotations

import contextlib
import json
import os
import urllib.error
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import yaml

from model_audit.catalog_ops import incomplete_model_modalities, retain_documented_models

from .canonical import write_catalog
from .model_kind import text_only
from .outcomes import FetchedModels, ModelAcquisition, ModelFetchFailed, ModelsFetched, SkippedModels, UnknownProvidersError
from .parameter_support import apply_discovery_evidence, discovery_evidence
from .paths import TAXONOMY
from .sources import registry
from .sources.base import GenericModelSource
from .types import object_list, object_or_empty, required_string, strings

if TYPE_CHECKING:
    from .sources.base import ModelSource
    from .types import CatalogObject

ROOT = TAXONOMY
OUT = ROOT / "models"


def configured_source(provider: str, configuration: CatalogObject, sources: dict[str, ModelSource]) -> ModelSource:
    source = sources.get(provider)
    if source is not None:
        return source
    source = GenericModelSource()
    source.provider_id = provider
    source.url = required_string(configuration.get("models_url"), f"{provider} models URL")
    auth = (strings(configuration.get("auth")) or ["bearer"])[0]
    source.auth = f"header:{auth.split(':', 1)[1]}" if auth.startswith("header_key:") else auth
    return source


def acquire(  # noqa: PLR0911 acquisition guard clauses return one explicit provider status
    provider: str, configuration: CatalogObject, source: ModelSource, stamp: str
) -> ModelAcquisition:
    url = required_string(configuration.get("models_url"), f"{provider} models URL")
    if "{" in url:
        return SkippedModels(provider, f"account-scoped endpoint, resolve {url}")

    key = None
    if not source.open_access:
        env_var = required_string(configuration.get("env_var"), f"{provider} credential environment variable")
        key = os.environ.get(env_var)
        if not key:
            return SkippedModels(provider, f"no {env_var} in environment")

    try:
        payload = source.fetch(key)
        raw_models = source.items(payload)
        models = text_only(source.enrich([model for model in (source.normalize(item) for item in raw_models) if model is not None]))
    except urllib.error.HTTPError as error:
        detail = ""
        with contextlib.suppress(UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            detail = ": " + (json.loads(error.read().decode()).get("error") or {}).get("message", "")[:110]
        return ModelFetchFailed(provider, f"HTTP {error.code}{detail}")
    except Exception as error:  # noqa: BLE001 provider failures are reported independently so one vendor cannot stop the catalog
        return ModelFetchFailed(provider, f"{type(error).__name__}: {str(error)[:110]}")

    if raw_models and not models:
        return ModelFetchFailed(provider, f"{len(raw_models)} returned, none kept; check the module's filter")
    if not models:
        return ModelFetchFailed(provider, "empty or unrecognized payload")
    if incomplete := incomplete_model_modalities(provider, models):
        return ModelFetchFailed(provider, f"models without required modalities: {', '.join(incomplete)}")

    target = OUT / f"{provider}.json"
    previous_models = object_list(object_or_empty(json.loads(target.read_text(), parse_float=Decimal)).get("models")) if target.exists() else []
    previous_ids = {model["id"] for model in previous_models}
    models = apply_discovery_evidence(models, discovery_evidence(configuration, ROOT))
    models = retain_documented_models(models, previous_models)
    declared = sum(1 for model in models if model.get("context_length") or model.get("supports_tools") is not None)
    new_models = sum(1 for model in models if model["id"] not in previous_ids)
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
    return FetchedModels(provider, len(models), declared, new_models)


def run(providers: tuple[str, ...] = ()) -> ModelsFetched:
    entries = {provider["id"]: provider for provider in yaml.safe_load((ROOT / "providers.yml").read_text())["providers"]}
    selected = set(providers) or set(entries)
    unknown = selected - set(entries)
    if unknown:
        raise UnknownProvidersError(unknown, "providers.yml")

    OUT.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    sources = registry()
    results = tuple(
        acquire(provider, entries[provider], configured_source(provider, entries[provider], sources), stamp) for provider in sorted(selected)
    )
    return ModelsFetched(results, required=bool(providers))
