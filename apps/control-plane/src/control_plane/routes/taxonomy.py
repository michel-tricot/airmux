from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import col

from control_plane.deps import InstanceDep, MgmtDep  # noqa: TC001 FastAPI resolves dependency annotations at runtime
from control_plane.models import Model, Provider
from control_plane.schemas import Envelope
from control_plane.taxonomy import ModelIn, ProviderIn, UnknownProviderError, upsert_model, upsert_provider

router = APIRouter(prefix="/taxonomy")


class ProviderOut(BaseModel):
    provider_id: str


class ModelOut(BaseModel):
    model_id: str


class TaxonomyOut(BaseModel):
    providers: list[Provider]
    models: list[Model]


@router.get("")
async def get_taxonomy(_claims: MgmtDep) -> Envelope[TaxonomyOut]:
    """The instance-wide catalog, readable by any management token."""
    return Envelope(
        data=TaxonomyOut(
            providers=await Provider.find(order_by=col(Provider.id)),
            models=await Model.find(order_by=col(Model.id)),
        )
    )


@router.post("/providers")
async def create_provider(_claims: InstanceDep, body: ProviderIn) -> Envelope[ProviderOut]:
    """Create or update: reapplying a taxonomy converges the catalog."""
    await upsert_provider(body)
    return Envelope(data=ProviderOut(provider_id=body.provider_id))


@router.post("/models")
async def create_model(_claims: InstanceDep, body: ModelIn) -> Envelope[ModelOut]:
    """Create or update: reapplying a taxonomy converges the catalog."""
    try:
        await upsert_model(body)
    except UnknownProviderError:
        raise HTTPException(status_code=404) from None
    return Envelope(data=ModelOut(model_id=body.model_id))
