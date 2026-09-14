from __future__ import annotations

from uuid import UUID  # noqa: TC003 fastapi resolves return annotations at runtime

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import col

from control_plane.authz import Permission
from control_plane.deps import OrgDep, instance_scope, org_scope, require
from control_plane.models import Org
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.org import OrgCreate, OrgOut, OrgUpdate
from control_plane.routes.provider_credentials import secret_store

router = APIRouter(prefix="/organizations")


@router.post("", tags=["Instance Organizations"], dependencies=[require("api", instance_scope, Permission.organizations_create)])
async def create_org(body: OrgCreate) -> Envelope[OrgOut]:
    """Create an organization."""
    org = await Org.create(body.name, body.slug)
    return Envelope(data=OrgOut.model_validate(org))


@router.patch("/{org_id}", tags=["Organization Settings"], dependencies=[require("api", org_scope, Permission.organizations_update)])
async def update_org(org_id: OrgDep, body: OrgUpdate) -> Envelope[OrgOut]:
    """Update an organization's mutable fields."""
    org = await Org.find_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return Envelope(data=OrgOut.model_validate(await org.apply(body).save()))


@router.get("", tags=["Instance Organizations"], dependencies=[require("api", instance_scope, Permission.organizations_read)])
async def list_orgs() -> Envelope[list[OrgOut]]:
    """List every organization on the instance."""
    return Envelope(data=[OrgOut.model_validate(r) for r in await Org.find(order_by=col(Org.name))])


@router.get("/{org_id}", tags=["Organization Settings"], dependencies=[require("api", org_scope, Permission.organizations_read)])
async def get_org(org_id: OrgDep) -> Envelope[OrgOut]:
    """Return one organization."""
    org = await Org.find_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return Envelope(data=OrgOut.model_validate(org))


@router.delete("/{org_id}", tags=["Organization Settings"], dependencies=[require("api", org_scope, Permission.organizations_delete)])
async def delete_org(org_id: OrgDep, request: Request) -> Envelope[DeletedOut[UUID]]:
    """Delete an organization and its workspaces, keys, credentials, memberships, and bundles.

    Historical usage events and audit entries are retained.
    """
    org = await Org.find_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    await org.delete_with_contents(secret_store(request))
    return Envelope(data=DeletedOut.of(org_id))
