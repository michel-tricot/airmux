from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, Field

from control_plane.models import Model, Provider
from control_plane.routes.org import ModelIn, ProviderIn

if TYPE_CHECKING:
    from pathlib import Path


class TaxonomyConflictError(Exception):
    """A provider or model id in the taxonomy already belongs to another org."""


class TaxonomySpec(BaseModel):
    providers: list[ProviderIn] = Field(default_factory=list)
    models: list[ModelIn] = Field(default_factory=list)


def parse_taxonomy(path: Path) -> TaxonomySpec:
    return TaxonomySpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


async def apply_taxonomy(spec: TaxonomySpec, org_id: str) -> tuple[int, int]:
    """Converge the org's catalog on the taxonomy: create missing providers and models, update existing ones.

    Entries absent from the taxonomy are left alone; removal stays an explicit API operation.
    """
    for p in spec.providers:
        provider = await Provider.get(p.provider_id)
        if provider is not None and provider.org_id != org_id:
            raise TaxonomyConflictError(p.provider_id)
        if provider is None:
            provider = Provider(id=p.provider_id, org_id=org_id, kind=p.kind, base_url=p.base_url, credential_ref=p.credential_ref)
        else:
            provider.kind = p.kind
            provider.base_url = p.base_url
            provider.credential_ref = p.credential_ref
        provider.cache_read_multiplier = p.cache_read_multiplier
        provider.cache_write_multiplier = p.cache_write_multiplier
        await provider.save()
    for m in spec.models:
        model = await Model.get(m.model_id)
        if model is not None and model.org_id != org_id:
            raise TaxonomyConflictError(m.model_id)
        if model is None:
            model = Model(
                id=m.model_id,
                org_id=org_id,
                provider_id=m.provider_id,
                upstream_model=m.upstream_model or m.model_id,
                input_price_per_mtok=m.input_price_per_mtok,
                output_price_per_mtok=m.output_price_per_mtok,
                context_window=m.context_window,
                max_output_tokens=m.max_output_tokens,
                capabilities=m.capabilities,
            )
        else:
            model.provider_id = m.provider_id
            model.upstream_model = m.upstream_model or m.model_id
            model.input_price_per_mtok = m.input_price_per_mtok
            model.output_price_per_mtok = m.output_price_per_mtok
            model.context_window = m.context_window
            model.max_output_tokens = m.max_output_tokens
            model.capabilities = m.capabilities
        await model.save()
    return len(spec.providers), len(spec.models)
