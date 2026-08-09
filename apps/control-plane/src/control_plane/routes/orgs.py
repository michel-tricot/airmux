from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col

from control_plane.authz import Scope
from control_plane.deps import instance_scope, require
from control_plane.models import Org
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.org import OrgCreate, OrgOut, OrgUpdate

router = APIRouter(prefix="/orgs", dependencies=[Depends(instance_scope)])


@router.post("", tags=["Orgs"], dependencies=[require(Scope.orgs_write)])
async def create_org(body: OrgCreate) -> Envelope[OrgOut]:
    org = await Org(name=body.name).save()
    return Envelope(data=OrgOut.model_validate(org))


@router.patch("/{org_id}", tags=["Orgs"], dependencies=[require(Scope.orgs_write)])
async def update_org(org_id: UUID, body: OrgUpdate) -> Envelope[OrgOut]:
    org = await Org.find_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=404)
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(org, name, value)
    return Envelope(data=OrgOut.model_validate(await org.save()))


@router.get("", tags=["Orgs"], dependencies=[require(Scope.orgs_read)])
async def list_orgs() -> Envelope[list[OrgOut]]:
    return Envelope(data=[OrgOut.model_validate(r) for r in await Org.find(order_by=col(Org.name))])


@router.get("/{org_id}", tags=["Orgs"], dependencies=[require(Scope.orgs_read)])
async def get_org(org_id: UUID) -> Envelope[OrgOut]:
    org = await Org.find_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=404)
    return Envelope(data=OrgOut.model_validate(org))


@router.delete("/{org_id}", tags=["Orgs"], dependencies=[require(Scope.orgs_write)])
async def delete_org(org_id: UUID) -> Envelope[DeletedOut[UUID]]:
    """Delete an org with everything scoped to it: its workspaces and their keys, its own keys, its memberships, its bundles.

    Its usage events stay. They are history keyed by ids, not rows belonging to the org, so they
    outlive it the way the audit trail does rather than standing in the way of the delete.
    """
    org = await Org.find_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=404)
    await org.delete_with_contents()
    return Envelope(data=DeletedOut(id=org_id, deleted_at=datetime.now(tz=UTC)))
