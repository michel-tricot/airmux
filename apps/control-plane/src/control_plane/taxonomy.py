from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from control_plane.models import Model, Provider
from control_plane.models.model import ModelOut
from control_plane.models.provider import ProviderOut

if TYPE_CHECKING:
    from pathlib import Path

ALLOWED_CREDENTIAL_SCHEMES = ("env:", "file:")


class TaxonomyError(Exception):
    """The taxonomy cannot be applied."""


class UnknownProviderError(TaxonomyError):
    """A model routes to a provider that does not exist."""


class ProviderIn(BaseModel):
    provider_id: str = Field(description="Provider name, e.g. openai")
    kind: Literal["openai_compatible", "anthropic"] = Field("openai_compatible", description="Adapter kind")
    base_url: str = Field(description="OpenAI-compatible endpoint, e.g. https://api.groq.com/openai/v1")
    credential_ref: str = Field(description="env: or file: reference resolved by the data plane, never a raw secret")
    cache_read_multiplier: float = Field(1.0, description="Input price factor for prompt-cache hits")
    cache_write_multiplier: float = Field(1.0, description="Input price factor for cache writes")

    @field_validator("credential_ref")
    @classmethod
    def credential_ref_is_a_reference(cls, v: str) -> str:
        if not v.startswith(ALLOWED_CREDENTIAL_SCHEMES):
            msg = "credential_ref must be an env: or file: reference resolved by the data plane, never a raw secret"
            raise ValueError(msg)
        return v


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
        provider = Provider(name=p.provider_id, kind=p.kind, base_url=p.base_url, credential_ref=p.credential_ref)
    else:
        provider.kind = p.kind
        provider.base_url = p.base_url
        provider.credential_ref = p.credential_ref
    provider.cache_read_multiplier = p.cache_read_multiplier
    provider.cache_write_multiplier = p.cache_write_multiplier
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
