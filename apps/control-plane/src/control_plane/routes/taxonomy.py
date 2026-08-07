from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlmodel import col

from control_plane.authz import Scope
from control_plane.deps import InstanceDep, MgmtDep, require
from control_plane.models import Model, Provider
from control_plane.models.model import ModelOut
from control_plane.models.provider import ProviderOut
from control_plane.schemas import Envelope
from control_plane.taxonomy import ModelIn, ProviderIn, TaxonomyOut, UnknownProviderError, upsert_model, upsert_provider

router = APIRouter(prefix="/taxonomy", tags=["Taxonomy"])


@router.get("", dependencies=[require(Scope.taxonomy_read)])
async def get_taxonomy(_claims: MgmtDep) -> Envelope[TaxonomyOut]:
    """The instance-wide catalog, readable by any management token."""
    return Envelope(
        data=TaxonomyOut(
            providers=[ProviderOut.model_validate(r) for r in await Provider.find(order_by=col(Provider.id))],
            models=[ModelOut.model_validate(r) for r in await Model.find(order_by=col(Model.id))],
        )
    )


@router.post("/providers", dependencies=[require(Scope.taxonomy_write)])
async def create_provider(_claims: InstanceDep, body: ProviderIn) -> Envelope[ProviderOut]:
    """Create or update: reapplying a taxonomy converges the catalog."""
    return Envelope(data=ProviderOut.model_validate(await upsert_provider(body)))


@router.post("/models", dependencies=[require(Scope.taxonomy_write)])
async def create_model(_claims: InstanceDep, body: ModelIn) -> Envelope[ModelOut]:
    """Create or update: reapplying a taxonomy converges the catalog."""
    try:
        model = await upsert_model(body)
    except UnknownProviderError:
        raise HTTPException(status_code=404) from None
    return Envelope(data=ModelOut.model_validate(model))
