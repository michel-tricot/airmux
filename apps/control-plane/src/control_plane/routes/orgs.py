from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col

from control_plane.authz import Scope
from control_plane.deps import instance_scope, require
from control_plane.models import Org
from control_plane.models.org import OrgCreate, OrgOut, OrgPatch
from control_plane.schemas import Envelope

router = APIRouter(prefix="/orgs", dependencies=[Depends(instance_scope)])


@router.post("", tags=["Orgs"], dependencies=[require(Scope.orgs_write)])
async def create_org(body: OrgCreate) -> Envelope[OrgOut]:
    if await Org.get(body.id) is not None:
        raise HTTPException(status_code=409)
    org = await Org(id=body.id, name=body.name or body.id).save()
    return Envelope(data=OrgOut.model_validate(org))


@router.patch("/{org_id}", tags=["Orgs"], dependencies=[require(Scope.orgs_write)])
async def update_org(org_id: str, body: OrgPatch) -> Envelope[OrgOut]:
    org = await Org.get(org_id)
    if org is None:
        raise HTTPException(status_code=404)
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(org, name, value)
    return Envelope(data=OrgOut.model_validate(await org.save()))


@router.get("", tags=["Orgs"], dependencies=[require(Scope.orgs_read)])
async def list_orgs() -> Envelope[list[OrgOut]]:
    return Envelope(data=[OrgOut.model_validate(r) for r in await Org.find(order_by=col(Org.id))])
