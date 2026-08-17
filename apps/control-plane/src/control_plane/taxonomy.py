from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator

from control_plane.models import Model, Provider
from control_plane.models.common.wire import RequestModel
from control_plane.models.model import ModelOut
from control_plane.models.provider import ProviderOut

if TYPE_CHECKING:
    from pathlib import Path


class UnknownProviderError(ValueError):
    pass


class ProviderIn(RequestModel):
    """An upstream provider endpoint and its request-profile settings."""

    provider_id: str = Field(description="Provider name, e.g. openai", min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    kind: Literal["openai_compatible", "openai_responses", "anthropic"] = Field("openai_compatible", description="Adapter kind")
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
    egress_kind: Literal["openai_compatible", "openai_responses", "anthropic"] | None = Field(None, description="Per-model egress adapter override")
    input_price_per_mtok: float = Field(0.0, ge=0, description="USD per million input tokens")
    output_price_per_mtok: float = Field(0.0, ge=0, description="USD per million output tokens")
    cache_read_price_per_mtok: float = Field(0.0, ge=0, description="USD per million cache-read input tokens")
    cache_write_price_per_mtok: float = Field(0.0, ge=0, description="USD per million cache-write input tokens")
    context_window: int = Field(128000, ge=1, le=100_000_000, description="Context window in tokens")
    max_output_tokens: int | None = Field(None, ge=1, le=100_000_000, description="Max completion tokens; requests are clamped to it")
    capabilities: list[str] = Field(default_factory=lambda: ["streaming", "tools"], max_length=128, description="Capabilities supported by the model")

    @field_validator("provider_id", mode="before")
    @classmethod
    def normalize_provider_id(cls, provider_id: object) -> object:
        return provider_id.strip().casefold() if isinstance(provider_id, str) else provider_id


class TaxonomySpec(RequestModel):
    providers: list[ProviderIn] = Field(default_factory=list, max_length=1000)
    models: list[ModelIn] = Field(default_factory=list, max_length=10000)


class TaxonomyOut(BaseModel):
    providers: list[ProviderOut]
    models: list[ModelOut]


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
        raise UnknownProviderError(m.provider_id)
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
            capabilities=m.capabilities,
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
        model.capabilities = m.capabilities
    return await model.save()


async def apply_taxonomy(spec: TaxonomySpec) -> tuple[int, int]:
    """Create or update every provider and model present in the taxonomy."""
    for p in spec.providers:
        await upsert_provider(p)
    for m in spec.models:
        await upsert_model(m)
    return len(spec.providers), len(spec.models)
