from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from control_plane.deps import ActingUserDep, user_scoped
from control_plane.models import Org, OrgMembership
from control_plane.models.common.wire import Envelope
from control_plane.models.org import OrgCreate, OrgOut

router = APIRouter(prefix="/enroll")


class EnrollOut(BaseModel):
    orgs: list[OrgOut]
    personal_org_id: UUID | None


@router.get("", tags=["Enrollment"], dependencies=[user_scoped()])
async def enrollment(user: ActingUserDep) -> Envelope[EnrollOut]:
    """The acting user's standing: their orgs by name, and whether their one personal org exists."""
    orgs = await Org.joined_by(user.id)
    personal = await Org.personal_of(user.id)
    return Envelope(data=EnrollOut(orgs=[OrgOut.model_validate(o) for o in orgs], personal_org_id=personal.id if personal else None))


@router.post("/org", tags=["Enrollment"], dependencies=[user_scoped()])
async def create_personal_org(body: OrgCreate, user: ActingUserDep) -> Envelope[OrgOut]:
    """Found the acting user's one personal org, with the creator as its first member.

    The unique personal_for column is the cap: the database refuses a second personal org
    however hard a credential races, so no scope or guard code is involved. Further orgs
    are admin-provisioned. The slot survives losing the membership; only deleting the
    personal org frees it.
    """
    if await Org.personal_of(user.id) is not None:
        raise HTTPException(status_code=409, detail="personal org already exists")
    org = await Org(name=body.name, personal_for=user.id).save()
    await OrgMembership(user_id=user.id, org_id=org.id).save()
    return Envelope(data=OrgOut.model_validate(org))
