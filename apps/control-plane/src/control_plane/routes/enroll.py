from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from control_plane.authority import visible_org_ids
from control_plane.authz import OrgRole
from control_plane.deps import ActingUserDep, ActorDep, CookieUserDep, browser_scoped, user_scoped
from control_plane.models import Org, OrgMembership
from control_plane.models.common.wire import Envelope
from control_plane.models.org import OrgCreate, OrgOut

router = APIRouter(prefix="/enroll")


class EnrollOut(BaseModel):
    orgs: list[OrgOut]
    personal_org_id: UUID | None


@router.get("", tags=["Enrollment"], dependencies=[user_scoped()])
async def enrollment(user: ActingUserDep, actor: ActorDep) -> Envelope[EnrollOut]:
    """List the organizations visible to the current user and identify their personal organization."""
    orgs = await Org.joined_by(user.id)
    visible = frozenset(visible_org_ids(actor, (org.id for org in orgs)))
    orgs = [org for org in orgs if org.id in visible]
    personal = await Org.personal_of(user.id)
    personal_visible = personal is not None and bool(visible_org_ids(actor, (personal.id,)))
    return Envelope(
        data=EnrollOut(orgs=[OrgOut.model_validate(org) for org in orgs], personal_org_id=personal.id if personal_visible and personal else None)
    )


@router.post("/org", tags=["Enrollment"], dependencies=[browser_scoped()])
async def create_personal_org(body: OrgCreate, user: CookieUserDep) -> Envelope[OrgOut]:
    """Create the current user's personal organization and make them its owner.

    A user can own one personal organization at a time. Deleting it allows another to be created.
    """
    if await Org.personal_of(user.id) is not None:
        raise HTTPException(status_code=409, detail="personal org already exists")
    org = await Org(name=body.name, personal_for=user.id).save()
    await OrgMembership(user_id=user.id, org_id=org.id, role=OrgRole.owner).save()
    return Envelope(data=OrgOut.model_validate(org))
