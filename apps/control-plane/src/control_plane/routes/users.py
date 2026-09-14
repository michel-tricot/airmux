"""The instance roster: creating principals and reading every user across the deployment.

Membership lives on the org router instead, because granting it is an org decision; taking the
org from the credential is what keeps a grant inside the scope the caller already holds.
"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, HTTPException
from sqlmodel import col

from control_plane.authz import Permission
from control_plane.deps import instance_scope, require
from control_plane.models import InferenceKey, Org, OrgMembership, User
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.user import InstanceRoleIn, LastInstanceOwnerError, ServiceAccountIn, UserOut

router = APIRouter()


@router.post("/service-accounts", tags=["Instance Users"], dependencies=[require("api", instance_scope, Permission.principals_manage)])
async def create_service_account(body: ServiceAccountIn) -> Envelope[UserOut]:
    """Create a machine principal with an optional instance role."""
    user = User.new_service_account(body.name, body.instance_role)
    return Envelope(data=_user_out(await user.save(), []))


def _user_out(u: User, orgs: list[UUID]) -> UserOut:
    return UserOut.model_validate({**u.model_dump(), "orgs": orgs})


@router.get("/users/{user_id}", tags=["Instance Users"], dependencies=[require("api", instance_scope, Permission.principals_read)])
async def get_user(user_id: UUID) -> Envelope[UserOut]:
    """Return one human user or service account and its organization memberships."""
    user = await User.find_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    memberships = await OrgMembership.find(OrgMembership.user_id == user_id, order_by=col(OrgMembership.org_id))
    return Envelope(data=_user_out(user, [m.org_id for m in memberships]))


@router.delete("/users/{user_id}", tags=["Instance Users"], dependencies=[require("api", instance_scope, Permission.principals_manage)])
async def delete_user(user_id: UUID) -> Envelope[DeletedOut[UUID]]:
    """Delete a principal and its login identities, sessions, and control-plane management keys.

    Remove organization memberships, personal organizations, and workspaces containing inference
    keys created by this principal before deleting it.
    """
    user = await User.find_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if await OrgMembership.first(OrgMembership.user_id == user_id) is not None:
        raise HTTPException(status_code=409, detail="user is still a member of an org; remove the memberships first")
    if await Org.personal_of(user_id) is not None:
        raise HTTPException(status_code=409, detail="user owns a personal org; delete the org first")
    if await InferenceKey.first(InferenceKey.user_id == user_id) is not None:
        raise HTTPException(status_code=409, detail="user created inference keys that outlive them; delete those workspaces first")
    try:
        await user.delete_with_contents()
    except LastInstanceOwnerError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Envelope(data=DeletedOut.of(user_id))


@router.get("/users", tags=["Instance Users"], dependencies=[require("api", instance_scope, Permission.principals_read)])
async def list_users(service_account: bool | None = None) -> Envelope[list[UserOut]]:
    """List human users and service accounts across the instance."""
    kind = [] if service_account is None else [User.service_account == service_account]
    users = await User.find(*kind, order_by=col(User.email))
    memberships = await OrgMembership.find(order_by=col(OrgMembership.org_id))
    orgs_by_user: dict[UUID, list[UUID]] = {}
    for m in memberships:
        orgs_by_user.setdefault(m.user_id, []).append(m.org_id)
    return Envelope(data=[_user_out(u, orgs_by_user.get(u.id, [])) for u in users])


@router.put("/users/{user_id}/instance-role", tags=["Instance Users"], dependencies=[require("api", instance_scope, Permission.principals_manage)])
async def change_instance_role(user_id: UUID, body: InstanceRoleIn) -> Envelope[UserOut]:
    try:
        user = await User.change_instance_role(user_id, body.instance_role)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    memberships = await OrgMembership.find(OrgMembership.user_id == user_id, order_by=col(OrgMembership.org_id))
    return Envelope(data=_user_out(user, [membership.org_id for membership in memberships]))
