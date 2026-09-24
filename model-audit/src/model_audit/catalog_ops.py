from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, Protocol, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from contract import Modality

if TYPE_CHECKING:
    from pathlib import Path

PROVIDERS_HEADER = """# Applied provider catalog. Maintain through airmux-audit providers onboard and sync.
# Agent field guidance: airmux-audit agent guide provider-onboarding

"""
CANDIDATES_HEADER = """# Providers tracked for future onboarding. Identity only; no derived catalog data.
# Promote through a typed provider source and airmux-audit providers onboard.

"""


class ProviderDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    homepage: str = Field(pattern=r"^https?://")
    docs: str = Field(pattern=r"^https?://")
    base_url: str = Field(pattern=r"^https?://")
    models_url: str = Field(pattern=r"^https?://")
    openapi: str | None = Field(None, pattern=r"^https?://")
    ingress: tuple[Literal["oai", "oai_responses", "anthropic", "google", "other_standard", "custom"], ...] = Field(min_length=1)
    primary_surface: Literal["oai", "oai_responses", "anthropic", "google", "other_standard", "custom"]
    auth: tuple[str, ...] = Field(min_length=1)
    env_var: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    icon_mono: str | None = None
    icon_color: str | None = None

    @model_validator(mode="after")
    def valid_primary_surface(self) -> ProviderDefinition:
        if self.primary_surface not in self.ingress:
            message = f"primary surface {self.primary_surface} is not one of {', '.join(self.ingress)}"
            raise ValueError(message)
        if len(self.auth) not in {1, len(self.ingress)}:
            message = "auth must contain one shared scheme or one scheme per ingress"
            raise ValueError(message)
        return self


class SchemaDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    surface: Literal["oai", "oai_responses", "anthropic", "google", "other_standard", "custom"]
    url: str = Field(pattern=r"^https?://")
    path_pattern: str


class ProviderSource(Protocol):
    provider_id: str
    url: str
    open_access: bool
    definition: ProviderDefinition | None
    schemas: tuple[SchemaDefinition, ...]
    documented_schemas: dict[str, dict[str, object]]

    def fetch(self, key: str | None) -> object: ...

    def items(self, payload: object) -> list[dict[str, object]]: ...

    def normalize(self, item: dict[str, object]) -> dict[str, object] | None: ...

    def enrich(self, models: list[dict[str, object]]) -> list[dict[str, object]]: ...


class ModelDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    source: str
    input_modalities: tuple[Modality, ...] = Field(min_length=1)
    output_modalities: tuple[Modality, ...] = Field(min_length=1)
    context_window: int | None = Field(None, ge=1)
    max_output_tokens: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def complete_limits(self) -> ModelDefinition:
        if (self.context_window is None) != (self.max_output_tokens is None):
            message = "context_window and max_output_tokens must be supplied together"
            raise ValueError(message)
        return self


def provider_sources() -> dict[str, ProviderSource]:
    from model_audit.catalog_tasks.sources import registry  # noqa: PLC0415 avoids a definition-time import cycle with provider modules

    return cast("dict[str, ProviderSource]", registry())


def incomplete_model_modalities(provider_id: str, models: list[dict[str, object]]) -> tuple[str, ...]:
    return tuple(
        f"{provider_id}/{model.get('id', '<unnamed>')}.{field}"
        for model in models
        for field in ("input_modalities", "output_modalities")
        if not isinstance(model.get(field), list) or not model[field]
    )


def preflight_source(source: ProviderSource, key: str | None) -> int:
    try:
        payload = source.fetch(key)
        raw = source.items(payload)
        models = [model for model in (source.normalize(item) for item in raw) if model is not None]
        models = source.enrich(models)
    except OSError as error:
        message = f"model acquisition failed: {error}"
        raise RuntimeError(message) from error
    if raw and not models:
        message = f"{len(raw)} models returned, none kept; check the provider source filter"
        raise RuntimeError(message)
    if not models:
        message = "the model endpoint returned an empty or unrecognized payload"
        raise RuntimeError(message)
    incomplete = incomplete_model_modalities(source.provider_id, models)
    if incomplete:
        message = f"models without required modalities: {', '.join(incomplete)}"
        raise RuntimeError(message)
    return len(models)


def load_provider_entries(taxonomy: Path) -> dict[str, dict[str, object]]:
    documents = (
        (yaml.safe_load(path.read_text(encoding="utf-8")) or {}, group)
        for filename, group in (("providers.yml", "providers"), ("routers.yml", "routers"))
        if (path := taxonomy / filename).exists()
    )
    return {str(provider["id"]): provider for document, group in documents for provider in document.get(group, ())}


def provider_entry(definition: ProviderDefinition) -> dict[str, object]:
    icon_mono = definition.icon_mono or definition.id
    return {
        "id": definition.id,
        "name": definition.name,
        "icon_mono": icon_mono,
        "icon_color": definition.icon_color or icon_mono,
        "homepage": str(definition.homepage),
        "docs": str(definition.docs),
        "base_url": str(definition.base_url),
        "openapi": str(definition.openapi) if definition.openapi is not None else None,
        "models_url": str(definition.models_url),
        "ingress": list(definition.ingress),
        "primary_surface": definition.primary_surface,
        "auth": list(definition.auth),
        "env_var": definition.env_var,
        "schema": None,
    }


def _monogram(name: str) -> str:
    letter = next((character.upper() for character in name if character.isalnum()), "A")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">'
        '<rect width="24" height="24" rx="6" fill="currentColor"/>'
        f'<text x="12" y="16" text-anchor="middle" font-family="sans-serif" font-size="12" fill="white">{letter}</text></svg>\n'
    )


def add_provider(root: Path, definition: ProviderDefinition, *, replace: bool = False) -> ProviderDefinition:
    taxonomy = root / "taxonomy"
    taxonomy.mkdir(parents=True, exist_ok=True)
    providers_path = taxonomy / "providers.yml"
    document = yaml.safe_load(providers_path.read_text(encoding="utf-8")) if providers_path.exists() else {"providers": []}
    existing = next((provider for provider in document["providers"] if provider["id"] == definition.id), None)
    if existing is not None and not replace:
        message = f"provider {definition.id} already exists; pass --replace to update it"
        raise ValueError(message)
    entry = provider_entry(definition)
    if existing is not None:
        entry["schema"] = existing.get("schema")
    providers = [entry if provider["id"] == definition.id else provider for provider in document["providers"]]
    if existing is None:
        providers.append(entry)
    provider_document = yaml.safe_dump({"providers": providers}, sort_keys=False, width=150, allow_unicode=True)
    providers_path.write_text(PROVIDERS_HEADER + provider_document, encoding="utf-8")
    icon = taxonomy / "icons" / f"{definition.icon_mono or definition.id}.svg"
    icon.parent.mkdir(parents=True, exist_ok=True)
    if not icon.exists():
        icon.write_text(_monogram(definition.name), encoding="utf-8")
    candidates_path = taxonomy / "candidates.yml"
    if candidates_path.exists():
        candidates_document = yaml.safe_load(candidates_path.read_text(encoding="utf-8")) or {"candidates": []}
        candidates = [candidate for candidate in candidates_document["candidates"] if candidate["id"] != definition.id]
        candidate_document = yaml.safe_dump({"candidates": candidates}, sort_keys=False, width=150, allow_unicode=True)
        candidates_path.write_text(CANDIDATES_HEADER + candidate_document, encoding="utf-8")
    return definition


def retain_documented_models(acquired_models: list[dict[str, object]], previous_models: list[dict[str, object]]) -> list[dict[str, object]]:
    acquired_ids = {model.get("id") for model in acquired_models}
    documented_models = [model for model in previous_models if model.get("source") and model.get("id") not in acquired_ids]
    return [*acquired_models, *documented_models]


def add_model(root: Path, provider_id: str, definition: ModelDefinition, *, replace: bool = False) -> Path:
    providers_path = root / "taxonomy" / "providers.yml"
    providers = yaml.safe_load(providers_path.read_text(encoding="utf-8"))["providers"]
    if provider_id not in {provider["id"] for provider in providers}:
        message = f"provider {provider_id} is not in providers.yml"
        raise ValueError(message)
    path = root / "taxonomy" / "models" / f"{provider_id}.json"
    document: dict[str, object]
    if path.exists():
        document = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal))
    else:
        document = {
            "provider": provider_id,
            "source": definition.source,
            "source_type": "docs",
            "updated": datetime.now(tz=UTC).date().isoformat(),
            "models": [],
        }
    model_values = document.get("models")
    existing = cast("list[object]", model_values) if isinstance(model_values, list) else []
    previous = next((cast("dict[str, object]", model) for model in existing if isinstance(model, dict) and model.get("id") == definition.id), None)
    if previous is not None and not replace:
        message = f"model {provider_id}/{definition.id} already exists; pass --replace to update it"
        raise ValueError(message)
    models = [cast("dict[str, object]", model) for model in existing if isinstance(model, dict) and model.get("id") != definition.id]
    model = {
        **(previous or {}),
        "id": definition.id,
        "kind": "text",
        "source": definition.source,
        "input_modalities": list(definition.input_modalities),
        "output_modalities": list(definition.output_modalities),
    }
    if definition.context_window is not None:
        model.update(
            {
                "context_length": definition.context_window,
                "max_output_tokens": definition.max_output_tokens,
                "context_source": "vendor-docs",
                "max_output_source": "vendor-docs",
                "documentation_url": definition.source,
            }
        )
    models.append(model)
    models.sort(key=lambda model: str(model.get("id")))
    document.setdefault("source", definition.source)
    document.setdefault("source_type", "docs")
    document["count"] = len(models)
    document["models"] = models
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path
