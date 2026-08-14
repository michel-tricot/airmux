from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from control_plane.models import Model, Provider
from control_plane.models.model import ModelOut
from control_plane.models.provider import ProviderOut

if TYPE_CHECKING:
    from pathlib import Path


class TaxonomyError(Exception):
    """The taxonomy cannot be applied."""


class UnknownProviderError(TaxonomyError):
    """A model routes to a provider that does not exist."""


class ProviderIn(BaseModel):
    """How to reach a provider, not how to authenticate to it: credentials are their own resource.

    Extra keys are refused so a taxonomy still carrying credential_ref fails loudly. Ignoring it
    would leave the operator believing they configured a credential when the provider has none.
    """

    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(description="Provider name, e.g. openai")
    kind: Literal["openai_compatible", "anthropic"] = Field("openai_compatible", description="Adapter kind")
    base_url: str = Field(description="OpenAI-compatible endpoint, e.g. https://api.groq.com/openai/v1")
    icon: str = Field(
        "",
        description=(
            "Provider mark as a standalone 24x24 SVG document, empty when the provider has none. "
            "Carried as markup so adding a provider needs no client change to make it recognisable, "
            "which makes it untrusted markup to whatever renders it; sanitize at the render site"
        ),
    )
    cache_read_multiplier: float = Field(1.0, description="Input price factor for prompt-cache hits")
    cache_write_multiplier: float = Field(1.0, description="Input price factor for cache writes")
    param_aliases: dict[str, str] = Field(default_factory=dict, description="Canonical param name to this provider's spelling")
    accepted_params: list[str] | None = Field(None, description="Params known accepted beyond the core; consulted when params_closed")
    params_closed: bool = Field(False, description="True when the provider's request schema rejects unknown params")


class ModelIn(BaseModel):
    model_id: str = Field(description="Caller-facing model name")
    provider_id: str = Field(description="Provider id the model routes to")
    upstream_model: str = Field("", description="Model name sent to the provider, lets model_id be an alias; defaults to model_id")
    input_price_per_mtok: float = Field(0.0, description="USD per million input tokens")
    output_price_per_mtok: float = Field(0.0, description="USD per million output tokens")
    context_window: int = Field(128000, description="Context window in tokens")
    max_output_tokens: int | None = Field(None, description="Max completion tokens; requests are clamped to it")
    capabilities: list[str] = Field(default=["streaming", "tools"], description="Capabilities, comma separated")


class TaxonomySpec(BaseModel):
    providers: list[ProviderIn] = Field(default_factory=list)
    models: list[ModelIn] = Field(default_factory=list)


class TaxonomyOut(BaseModel):
    providers: list[ProviderOut]
    models: list[ModelOut]


def parse_taxonomy(path: Path) -> TaxonomySpec:
    return TaxonomySpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


async def upsert_provider(p: ProviderIn) -> Provider:
    """Create or update by name; the single upsert shared by the API route and taxonomy application."""
    provider = await Provider.first(Provider.name == p.provider_id)
    if provider is None:
        provider = Provider(name=p.provider_id, kind=p.kind, base_url=p.base_url)
    else:
        provider.kind = p.kind
        provider.base_url = p.base_url
    provider.icon = p.icon
    provider.cache_read_multiplier = p.cache_read_multiplier
    provider.cache_write_multiplier = p.cache_write_multiplier
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
            input_price_per_mtok=m.input_price_per_mtok,
            output_price_per_mtok=m.output_price_per_mtok,
            context_window=m.context_window,
            max_output_tokens=m.max_output_tokens,
            capabilities=m.capabilities,
        )
    else:
        model.provider_id = provider.id
        model.upstream_model = m.upstream_model or m.model_id
        model.input_price_per_mtok = m.input_price_per_mtok
        model.output_price_per_mtok = m.output_price_per_mtok
        model.context_window = m.context_window
        model.max_output_tokens = m.max_output_tokens
        model.capabilities = m.capabilities
    return await model.save()


async def apply_taxonomy(spec: TaxonomySpec) -> tuple[int, int]:
    """Converge the instance catalog on the taxonomy: create missing providers and models, update existing ones.

    Entries absent from the taxonomy are left alone; removal stays an explicit API operation.
    """
    for p in spec.providers:
        await upsert_provider(p)
    for m in spec.models:
        await upsert_model(m)
    return len(spec.providers), len(spec.models)
