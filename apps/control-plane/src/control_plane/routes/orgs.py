from __future__ import annotations

from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import col

from control_plane.authz import Permission
from control_plane.deps import instance_target, named_org_target, require
from control_plane.models import Org
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.org import OrgCreate, OrgOut, OrgUpdate
from control_plane.routes.provider_credentials import secret_store

router = APIRouter(prefix="/orgs")


@router.post("", tags=["Orgs"], dependencies=[require(Permission.organizations_create, instance_target)])
async def create_org(body: OrgCreate) -> Envelope[OrgOut]:
    org = await Org(name=body.name).save()
    return Envelope(data=OrgOut.model_validate(org))


@router.patch("/{org_id}", tags=["Orgs"], dependencies=[require(Permission.organizations_update, named_org_target)])
async def update_org(org_id: UUID, body: OrgUpdate) -> Envelope[OrgOut]:
    org = await Org.find_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return Envelope(data=OrgOut.model_validate(await org.apply(body).save()))


@router.get("", tags=["Orgs"], dependencies=[require(Permission.organizations_read, instance_target)])
async def list_orgs() -> Envelope[list[OrgOut]]:
    return Envelope(data=[OrgOut.model_validate(r) for r in await Org.find(order_by=col(Org.name))])


@router.get("/{org_id}", tags=["Orgs"], dependencies=[require(Permission.organizations_read, named_org_target)])
async def get_org(org_id: UUID) -> Envelope[OrgOut]:
    org = await Org.find_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return Envelope(data=OrgOut.model_validate(org))


@router.delete("/{org_id}", tags=["Orgs"], dependencies=[require(Permission.organizations_delete, named_org_target)])
async def delete_org(org_id: UUID, request: Request) -> Envelope[DeletedOut[UUID]]:
    """Delete an org with everything scoped to it: its workspaces and their keys, the provider
    credentials it brought, its own keys, its memberships, its bundles.

    Its usage events stay. They are history keyed by ids, not rows belonging to the org, so they
    outlive it the way the audit trail does rather than standing in the way of the delete.
    """
    org = await Org.find_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    await org.delete_with_contents(secret_store(request))
    return Envelope(data=DeletedOut.of(org_id))
