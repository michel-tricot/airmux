from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from contract.model_types import Capability, Modality, ParameterSupport

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Self


class _TaxonomyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _default_capabilities() -> list[Capability]:
    return ["streaming", "tools"]


class ProviderSpec(_TaxonomyInput):
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


class ModelSpec(_TaxonomyInput):
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


class TaxonomySpec(_TaxonomyInput):
    providers: list[ProviderSpec] = Field(default_factory=list, max_length=1000, description="Provider endpoints to create or update")
    models: list[ModelSpec] = Field(default_factory=list, max_length=10000, description="Routable models to create or update")

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


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)
