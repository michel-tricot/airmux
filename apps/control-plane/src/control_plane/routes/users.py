"""The instance roster: creating principals and reading every user across the deployment.

Membership lives on the org router instead, because granting it is an org decision; taking the
org from the credential is what keeps a grant inside the scope the caller already holds.
"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col

from control_plane.authz import Scope
from control_plane.deps import instance_scope, require
from control_plane.models import OrgMembership, User
from control_plane.models.common.wire import Envelope
from control_plane.models.user import ServiceAccountIn, UserCreate, UserOut

router = APIRouter(dependencies=[Depends(instance_scope)])


@router.post("/users", tags=["Users"], dependencies=[require(Scope.users_write)])
async def create_user(body: UserCreate) -> Envelope[UserOut]:
    if await User.first(User.email == body.email) is not None:
        raise HTTPException(status_code=409)
    user = User(email=body.email, name=body.name or body.email, service_account=False)
    return Envelope(data=_user_out(await user.save(), []))


@router.post("/service-accounts", tags=["Users"], dependencies=[require(Scope.users_write)])
async def create_service_account(body: ServiceAccountIn) -> Envelope[UserOut]:
    user = User.new_service_account(body.name)
    return Envelope(data=_user_out(await user.save(), []))


def _user_out(u: User, orgs: list[UUID]) -> UserOut:
    return UserOut.model_validate({**u.model_dump(), "orgs": orgs})


@router.get("/users", tags=["Users"], dependencies=[require(Scope.users_read)])
async def list_users() -> Envelope[list[UserOut]]:
    users = await User.find(order_by=col(User.email))
    memberships = await OrgMembership.find(order_by=col(OrgMembership.org_id))
    orgs_by_user: dict[UUID, list[UUID]] = {}
    for m in memberships:
        orgs_by_user.setdefault(m.user_id, []).append(m.org_id)
    return Envelope(data=[_user_out(u, orgs_by_user.get(u.id, [])) for u in users])
