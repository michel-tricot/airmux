from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlmodel import col

from control_plane.authz import Permission
from control_plane.deps import instance_scope, org_scope, require, workspace_scope
from control_plane.models import Model, Provider
from control_plane.models.common.wire import Envelope
from control_plane.models.model import ModelOut
from control_plane.models.provider import ProviderOut
from control_plane.taxonomy import ModelIn, ProviderIn, TaxonomyOut, UnknownProviderError, upsert_model, upsert_provider

router = APIRouter()


async def _taxonomy() -> Envelope[TaxonomyOut]:
    return Envelope(
        data=TaxonomyOut(
            providers=[ProviderOut.model_validate(provider) for provider in await Provider.find(order_by=col(Provider.name))],
            models=[ModelOut.model_validate(model) for model in await Model.find(order_by=col(Model.name))],
        )
    )


@router.get("/instance/taxonomy", tags=["Instance Model Catalog"], dependencies=[require(Permission.catalog_read, instance_scope)])
async def get_instance_taxonomy() -> Envelope[TaxonomyOut]:
    """Return the provider and model catalog at instance scope."""
    return await _taxonomy()


@router.get("/orgs/{org_id}/taxonomy", tags=["Organization Model Catalog"], dependencies=[require(Permission.catalog_read, org_scope)])
async def get_org_taxonomy() -> Envelope[TaxonomyOut]:
    """Return the provider and model catalog available to an organization."""
    return await _taxonomy()


@router.get(
    "/orgs/{org_id}/workspaces/{workspace_ref}/taxonomy",
    tags=["Workspace Model Catalog"],
    dependencies=[require(Permission.catalog_read, workspace_scope)],
)
async def get_workspace_taxonomy() -> Envelope[TaxonomyOut]:
    """Return the provider and model catalog available to a workspace."""
    return await _taxonomy()


@router.post("/instance/taxonomy/providers", tags=["Instance Model Catalog"], dependencies=[require(Permission.catalog_manage, instance_scope)])
async def create_provider(body: ProviderIn) -> Envelope[ProviderOut]:
    """Create a provider or replace the catalog entry with the same name."""
    return Envelope(data=ProviderOut.model_validate(await upsert_provider(body)))


@router.post("/instance/taxonomy/models", tags=["Instance Model Catalog"], dependencies=[require(Permission.catalog_manage, instance_scope)])
async def create_model(body: ModelIn) -> Envelope[ModelOut]:
    """Create a model or replace the catalog entry with the same name."""
    try:
        model = await upsert_model(body)
    except UnknownProviderError:
        raise HTTPException(status_code=404, detail="Provider not found; create it before its models") from None
    return Envelope(data=ModelOut.model_validate(model))
