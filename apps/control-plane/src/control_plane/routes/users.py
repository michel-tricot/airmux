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
from control_plane.models import InferenceKey, Org, OrgMembership, User
from control_plane.models.common.wire import DeletedOut, Envelope
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


@router.get("/users/{user_id}", tags=["Users"], dependencies=[require(Scope.users_read)])
async def get_user(user_id: UUID) -> Envelope[UserOut]:
    user = await User.find_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404)
    memberships = await OrgMembership.find(OrgMembership.user_id == user_id, order_by=col(OrgMembership.org_id))
    return Envelope(data=_user_out(user, [m.org_id for m in memberships]))


@router.delete("/users/{user_id}", tags=["Users"], dependencies=[require(Scope.users_write)])
async def delete_user(user_id: UUID) -> Envelope[DeletedOut[UUID]]:
    """Delete a user with the credentials that are theirs alone: identities, sessions, management and instance keys.

    Everything else a user touches outlives them, so it blocks the delete instead of following it:
    a membership is the org's decision to revisit, a personal org is a tenant, and an inference key
    belongs to its workspace and merely records who minted it.
    """
    user = await User.find_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404)
    if await OrgMembership.first(OrgMembership.user_id == user_id) is not None:
        raise HTTPException(status_code=409, detail="user is still a member of an org; remove the memberships first")
    if await Org.personal_of(user_id) is not None:
        raise HTTPException(status_code=409, detail="user owns a personal org; delete the org first")
    if await InferenceKey.first(InferenceKey.user_id == user_id) is not None:
        raise HTTPException(status_code=409, detail="user minted inference keys that outlive them; delete those workspaces first")
    await user.delete_with_contents()
    return Envelope(data=DeletedOut.of(user_id))


@router.get("/users", tags=["Users"], dependencies=[require(Scope.users_read)])
async def list_users(service_account: bool | None = None) -> Envelope[list[UserOut]]:
    """Every principal on the instance, or one kind of them: service_account splits the machines from the humans."""
    kind = [] if service_account is None else [User.service_account == service_account]
    users = await User.find(*kind, order_by=col(User.email))
    memberships = await OrgMembership.find(order_by=col(OrgMembership.org_id))
    orgs_by_user: dict[UUID, list[UUID]] = {}
    for m in memberships:
        orgs_by_user.setdefault(m.user_id, []).append(m.org_id)
    return Envelope(data=[_user_out(u, orgs_by_user.get(u.id, [])) for u in users])
