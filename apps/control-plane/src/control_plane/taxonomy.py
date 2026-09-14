from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from contract import Capability, Modality, ParameterSupport  # noqa: TC001 pydantic resolves these annotations at runtime
from control_plane.models import Model, Provider
from control_plane.models.common.wire import RequestModel
from control_plane.models.model import ModelOut
from control_plane.models.provider import ProviderOut

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path
    from typing import Self


def _default_capabilities() -> list[Capability]:
    return ["streaming", "tools"]


@dataclass(frozen=True)
class UnknownProviderReference:
    provider_id: str
    model_id: str


class UnknownProviderError(ValueError):
    def __init__(self, reference: UnknownProviderReference, *additional_references: UnknownProviderReference) -> None:
        self.references = (reference, *additional_references)
        label = "reference" if not additional_references else "references"
        requirements = "; ".join(f"model '{missing.model_id}' requires provider '{missing.provider_id}'" for missing in self.references)
        super().__init__(f"Unknown provider {label}: {requirements}")


class ProviderIn(RequestModel):
    """An upstream provider endpoint and its request-profile settings."""

    provider_id: str = Field(description="Provider name, e.g. openai", min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    kind: str = Field("openai_compatible", description="Adapter kind", min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9_]*$")
    base_url: HttpUrl = Field(description="OpenAI-compatible endpoint, e.g. https://api.groq.com/openai/v1")
    icon: str = Field(
        "",
        max_length=65536,
        description=(
            "Provider mark as a standalone 24x24 SVG document, or an empty string when no icon is available. "
            "Clients must sanitize this untrusted markup before rendering it"
        ),
    )
    param_aliases: dict[str, str] = Field(default_factory=dict, max_length=256, description="Canonical param name to this provider's spelling")
    accepted_params: list[str] | None = Field(None, max_length=256, description="Params known accepted beyond the core; consulted when params_closed")
    params_closed: bool = Field(False, description="True when the provider's request schema rejects unknown params")

    @field_validator("provider_id", mode="before")
    @classmethod
    def normalize_provider_id(cls, provider_id: object) -> object:
        return provider_id.strip().casefold() if isinstance(provider_id, str) else provider_id


class ModelIn(RequestModel):
    model_id: str = Field(description="Caller-facing model name", min_length=1, max_length=255)
    provider_id: str = Field(description="Provider id the model routes to", min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    upstream_model: str = Field("", max_length=255, description="Model name sent to the provider, lets model_id be an alias; defaults to model_id")
    egress_kind: str | None = Field(
        None, description="Per-model egress adapter override", min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9_]*$"
    )
    input_price_per_mtok: float = Field(0.0, ge=0, description="USD per million input tokens")
    output_price_per_mtok: float = Field(0.0, ge=0, description="USD per million output tokens")
    cache_read_price_per_mtok: float = Field(0.0, ge=0, description="USD per million cache-read input tokens")
    cache_write_price_per_mtok: float = Field(0.0, ge=0, description="USD per million cache-write input tokens")
    context_window: int = Field(128000, ge=1, le=100_000_000, description="Context window in tokens")
    max_output_tokens: int | None = Field(None, ge=1, le=100_000_000, description="Max completion tokens; requests are clamped to it")
    input_modalities: list[Modality] = Field(min_length=1, max_length=16, description="Accepted input modalities")
    output_modalities: list[Modality] = Field(min_length=1, max_length=16, description="Produced output modalities")
    capabilities: list[Capability] = Field(default_factory=_default_capabilities, max_length=4, description="Capabilities supported by the model")
    parameter_support: dict[str, ParameterSupport] = Field(
        default_factory=dict,
        max_length=128,
        description="Known support for canonical request parameters; an absent parameter is unknown",
    )

    @field_validator("provider_id", mode="before")
    @classmethod
    def normalize_provider_id(cls, provider_id: object) -> object:
        return provider_id.strip().casefold() if isinstance(provider_id, str) else provider_id


class TaxonomySpec(RequestModel):
    providers: list[ProviderIn] = Field(default_factory=list, max_length=1000, description="Provider endpoints to create or update")
    models: list[ModelIn] = Field(default_factory=list, max_length=10000, description="Routable models to create or update")

    @model_validator(mode="after")
    def unique_entries(self) -> Self:
        duplicate_providers = _duplicates(provider.provider_id for provider in self.providers)
        duplicate_models = _duplicates(model.model_id for model in self.models)
        if duplicate_providers or duplicate_models:
            parts = [
                f"duplicate {kind}: {', '.join(values)}"
                for kind, values in (("providers", duplicate_providers), ("models", duplicate_models))
                if values
            ]
            raise ValueError("; ".join(parts))
        return self


class TaxonomyOut(BaseModel):
    providers: list[ProviderOut]
    models: list[ModelOut]


class TaxonomyChangeCounts(BaseModel):
    created: int
    updated: int
    unchanged: int


class TaxonomyPublicationOut(BaseModel):
    org_id: UUID
    version: int


class TaxonomyApplyOut(BaseModel):
    dry_run: bool
    providers: TaxonomyChangeCounts
    models: TaxonomyChangeCounts
    published: list[TaxonomyPublicationOut]


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def parse_taxonomy(path: Path) -> TaxonomySpec:
    return TaxonomySpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


async def upsert_provider(p: ProviderIn) -> Provider:
    """Create or update by name; the single upsert shared by the API route and taxonomy application."""
    provider = await Provider.first(Provider.name == p.provider_id)
    if provider is None:
        provider = Provider(name=p.provider_id, kind=p.kind, base_url=str(p.base_url))
    else:
        provider.kind = p.kind
        provider.base_url = str(p.base_url)
    provider.icon = p.icon
    provider.param_aliases = p.param_aliases
    provider.accepted_params = p.accepted_params
    provider.params_closed = p.params_closed
    return await provider.save()


async def upsert_model(m: ModelIn) -> Model:
    """Create or update by name; the single upsert shared by the API route and taxonomy application."""
    provider = await Provider.first(Provider.name == m.provider_id)
    if provider is None:
        raise UnknownProviderError(UnknownProviderReference(provider_id=m.provider_id, model_id=m.model_id))
    model = await Model.first(Model.name == m.model_id)
    if model is None:
        model = Model(
            name=m.model_id,
            provider_id=provider.id,
            upstream_model=m.upstream_model or m.model_id,
            egress_kind=m.egress_kind,
            input_price_per_mtok=m.input_price_per_mtok,
            output_price_per_mtok=m.output_price_per_mtok,
            cache_read_price_per_mtok=m.cache_read_price_per_mtok,
            cache_write_price_per_mtok=m.cache_write_price_per_mtok,
            context_window=m.context_window,
            max_output_tokens=m.max_output_tokens,
            input_modalities=m.input_modalities,
            output_modalities=m.output_modalities,
            capabilities=m.capabilities,
            parameter_support=m.parameter_support,
        )
    else:
        model.provider_id = provider.id
        model.upstream_model = m.upstream_model or m.model_id
        model.egress_kind = m.egress_kind
        model.input_price_per_mtok = m.input_price_per_mtok
        model.output_price_per_mtok = m.output_price_per_mtok
        model.cache_read_price_per_mtok = m.cache_read_price_per_mtok
        model.cache_write_price_per_mtok = m.cache_write_price_per_mtok
        model.context_window = m.context_window
        model.max_output_tokens = m.max_output_tokens
        model.input_modalities = m.input_modalities
        model.output_modalities = m.output_modalities
        model.capabilities = m.capabilities
        model.parameter_support = m.parameter_support
    return await model.save()


async def apply_taxonomy(spec: TaxonomySpec) -> tuple[int, int]:
    """Create or update every provider and model present in the taxonomy."""
    for p in spec.providers:
        await upsert_provider(p)
    for m in spec.models:
        await upsert_model(m)
    return len(spec.providers), len(spec.models)


def _provider_matches(provider: Provider, desired: ProviderIn) -> bool:
    return (
        provider.kind == desired.kind
        and provider.base_url == str(desired.base_url)
        and provider.icon == desired.icon
        and provider.param_aliases == desired.param_aliases
        and provider.accepted_params == desired.accepted_params
        and provider.params_closed == desired.params_closed
    )


def _model_matches(model: Model, desired: ModelIn, provider_names: dict[UUID, str]) -> bool:
    return (
        provider_names[model.provider_id] == desired.provider_id
        and model.upstream_model == (desired.upstream_model or desired.model_id)
        and model.egress_kind == desired.egress_kind
        and model.input_price_per_mtok == desired.input_price_per_mtok
        and model.output_price_per_mtok == desired.output_price_per_mtok
        and model.cache_read_price_per_mtok == desired.cache_read_price_per_mtok
        and model.cache_write_price_per_mtok == desired.cache_write_price_per_mtok
        and model.context_window == desired.context_window
        and model.max_output_tokens == desired.max_output_tokens
        and model.input_modalities == desired.input_modalities
        and model.output_modalities == desired.output_modalities
        and model.capabilities == desired.capabilities
        and model.parameter_support == desired.parameter_support
    )


def _change_counts[T, U](desired: list[T], existing: dict[str, U], key: Callable[[T], str], matches: Callable[[U, T], bool]) -> TaxonomyChangeCounts:
    created = sum(key(entry) not in existing for entry in desired)
    unchanged = sum(key(entry) in existing and matches(existing[key(entry)], entry) for entry in desired)
    return TaxonomyChangeCounts(created=created, updated=len(desired) - created - unchanged, unchanged=unchanged)


async def plan_taxonomy(spec: TaxonomySpec) -> tuple[TaxonomyChangeCounts, TaxonomyChangeCounts]:
    providers = await Provider.find()
    models = await Model.find()
    providers_by_name = {provider.name.casefold(): provider for provider in providers}
    provider_names = {provider.id: provider.name.casefold() for provider in providers}
    available_providers = providers_by_name.keys() | {provider.provider_id for provider in spec.providers}
    missing = tuple(
        UnknownProviderReference(provider_id=model.provider_id, model_id=model.model_id)
        for model in spec.models
        if model.provider_id not in available_providers
    )
    if missing:
        raise UnknownProviderError(missing[0], *missing[1:])
    models_by_name = {model.name: model for model in models}
    provider_counts = _change_counts(spec.providers, providers_by_name, lambda provider: provider.provider_id, _provider_matches)
    model_counts = _change_counts(
        spec.models,
        models_by_name,
        lambda model: model.model_id,
        lambda model, desired: _model_matches(model, desired, provider_names),
    )
    return provider_counts, model_counts
