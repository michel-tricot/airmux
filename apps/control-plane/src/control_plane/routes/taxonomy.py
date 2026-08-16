from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlmodel import col

from control_plane.authz import Permission
from control_plane.deps import instance_target, require, selected_target
from control_plane.models import Model, Provider
from control_plane.models.common.wire import Envelope
from control_plane.models.model import ModelOut
from control_plane.models.provider import ProviderOut
from control_plane.taxonomy import ModelIn, ProviderIn, TaxonomyOut, UnknownProviderError, upsert_model, upsert_provider

router = APIRouter(prefix="/taxonomy", tags=["Taxonomy"])


@router.get("", dependencies=[require(Permission.catalog_read, selected_target)])
async def get_taxonomy() -> Envelope[TaxonomyOut]:
    """The instance-wide catalog, readable where the principal and credential both carry catalog access."""
    return Envelope(
        data=TaxonomyOut(
            providers=[ProviderOut.model_validate(r) for r in await Provider.find(order_by=col(Provider.name))],
            models=[ModelOut.model_validate(r) for r in await Model.find(order_by=col(Model.name))],
        )
    )


@router.post("/providers", dependencies=[require(Permission.catalog_manage, instance_target)])
async def create_provider(body: ProviderIn) -> Envelope[ProviderOut]:
    """Create or update: reapplying a taxonomy converges the catalog."""
    return Envelope(data=ProviderOut.model_validate(await upsert_provider(body)))


@router.post("/models", dependencies=[require(Permission.catalog_manage, instance_target)])
async def create_model(body: ModelIn) -> Envelope[ModelOut]:
    """Create or update: reapplying a taxonomy converges the catalog."""
    try:
        model = await upsert_model(body)
    except UnknownProviderError:
        raise HTTPException(status_code=404, detail="Provider not found; create it before its models") from None
    return Envelope(data=ModelOut.model_validate(model))
