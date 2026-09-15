from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from sqlmodel import col

from control_plane.authz import Permission
from control_plane.compiler import publish_changes
from control_plane.deps import instance_scope, org_scope, require, workspace_scope
from control_plane.models import Model, Provider
from control_plane.models.common.wire import Envelope
from control_plane.models.model import ModelIn, ModelOut
from control_plane.models.provider import ProviderIn, ProviderOut
from control_plane.taxonomy import (
    TaxonomyApplyOut,
    TaxonomyOut,
    TaxonomyPublicationOut,
    TaxonomySpec,
    apply_taxonomy,
    plan_taxonomy,
    upsert_model,
    upsert_provider,
)

router = APIRouter()


async def _taxonomy() -> Envelope[TaxonomyOut]:
    return Envelope(
        data=TaxonomyOut(
            providers=[ProviderOut.model_validate(provider) for provider in await Provider.find(order_by=col(Provider.name))],
            models=[ModelOut.model_validate(model) for model in await Model.find(order_by=col(Model.name))],
        )
    )


@router.get("/instance/taxonomy", tags=["Instance Model Catalog"], dependencies=[require("api", instance_scope, Permission.catalog_read)])
async def get_instance_taxonomy() -> Envelope[TaxonomyOut]:
    """Return the provider and model catalog at instance scope."""
    return await _taxonomy()


@router.post("/instance/taxonomy", tags=["Instance Model Catalog"], dependencies=[require("api", instance_scope, Permission.catalog_manage)])
async def apply_instance_taxonomy(
    body: TaxonomySpec,
    dry_run: Annotated[bool, Query(description="Validate and report changes without applying them")] = False,
) -> Envelope[TaxonomyApplyOut]:
    """Apply a complete provider and model taxonomy atomically."""
    provider_counts, model_counts = await plan_taxonomy(body)
    if dry_run:
        return Envelope(data=TaxonomyApplyOut(dry_run=True, providers=provider_counts, models=model_counts, published=[]))
    await apply_taxonomy(body)
    published = await publish_changes(datetime.now(tz=UTC))
    return Envelope(
        data=TaxonomyApplyOut(
            dry_run=False,
            providers=provider_counts,
            models=model_counts,
            published=[TaxonomyPublicationOut(org_id=bundle.org_id, version=bundle.version) for bundle in published],
        )
    )


@router.get(
    "/organizations/{org_id}/taxonomy", tags=["Organization Model Catalog"], dependencies=[require("api", org_scope, Permission.catalog_read)]
)
async def get_org_taxonomy() -> Envelope[TaxonomyOut]:
    """Return the provider and model catalog available to an organization."""
    return await _taxonomy()


@router.get(
    "/organizations/{org_id}/workspaces/{workspace_ref}/taxonomy",
    tags=["Workspace Model Catalog"],
    dependencies=[require("api", workspace_scope, Permission.catalog_read)],
)
async def get_workspace_taxonomy() -> Envelope[TaxonomyOut]:
    """Return the provider and model catalog available to a workspace."""
    return await _taxonomy()


@router.post(
    "/instance/taxonomy/providers", tags=["Instance Model Catalog"], dependencies=[require("api", instance_scope, Permission.catalog_manage)]
)
async def create_provider(body: ProviderIn) -> Envelope[ProviderOut]:
    """Create a provider or replace the catalog entry with the same name."""
    return Envelope(data=ProviderOut.model_validate(await upsert_provider(body)))


@router.post("/instance/taxonomy/models", tags=["Instance Model Catalog"], dependencies=[require("api", instance_scope, Permission.catalog_manage)])
async def create_model(body: ModelIn) -> Envelope[ModelOut]:
    """Create a model or replace the catalog entry with the same name."""
    return Envelope(data=ModelOut.model_validate(await upsert_model(body)))
