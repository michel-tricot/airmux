"""The instance roster: creating principals and reading every user across the deployment.

Membership lives on the org router instead, because granting it is an org decision; taking the
org from the credential is what keeps a grant inside the scope the caller already holds.
"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, HTTPException
from sqlmodel import col

from control_plane.authz import Permission, Scope
from control_plane.deps import ActorDep, instance_scope, require
from control_plane.models import Org, OrgMembership, User
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.management_key import ManagementKeyCreatedOut, ManagementKeyIn  # noqa: TC001 FastAPI resolves route annotations at runtime
from control_plane.models.user import InstanceRoleIn, ServiceAccountIn, UserMembershipsOut, UserOut
from control_plane.routes.management_keys import issue_management_key

router = APIRouter()


@router.post("/service-accounts", tags=["Instance Users"], dependencies=[require("api", instance_scope, Permission.principals_manage)])
async def create_service_account(body: ServiceAccountIn) -> Envelope[UserOut]:
    """Create a machine principal with an optional instance role."""
    user = User.new_service_account(body.name, body.instance_role)
    return Envelope(data=_user_out(await user.save(), []))


@router.post(
    "/service-accounts/{user_id}/management-keys",
    tags=["Instance Users"],
    dependencies=[require("api", instance_scope, Permission.management_keys_issue)],
)
async def create_instance_service_account_management_key(
    user_id: UUID,
    body: ManagementKeyIn,
    actor: ActorDep,
) -> Envelope[ManagementKeyCreatedOut]:
    """Issue an instance key for an instance-managed service account."""
    service_account = await User.instance_service_account(user_id)
    if service_account is None:
        raise HTTPException(status_code=404, detail="Instance service account not found")
    return Envelope(data=await issue_management_key(body, actor, Scope.instance(), principal_id=service_account.id))


def _user_out(user: User, orgs: list[UUID]) -> UserOut:
    return UserOut.model_validate({**user.model_dump(), "orgs": orgs})


@router.get("/users/{user_id}", tags=["Instance Users"], dependencies=[require("api", instance_scope, Permission.principals_read)])
async def get_user(user_id: UUID) -> Envelope[UserOut]:
    """Return one human user or service account and its organization memberships."""
    user = await User.find_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    memberships = await OrgMembership.find(OrgMembership.user_id == user_id, order_by=col(OrgMembership.org_id))
    return Envelope(data=_user_out(user, [membership.org_id for membership in memberships]))


@router.get("/users/{user_id}/memberships", tags=["Instance Users"], dependencies=[require("api", instance_scope, Permission.principals_read)])
async def get_user_memberships(user_id: UUID) -> Envelope[UserMembershipsOut]:
    user = await User.find_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return Envelope(data=await user.memberships())


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
    await user.delete_with_contents()
    return Envelope(data=DeletedOut.of(user_id))


@router.get("/users", tags=["Instance Users"], dependencies=[require("api", instance_scope, Permission.principals_read)])
async def list_users(service_account: bool | None = None) -> Envelope[list[UserOut]]:
    """List human users and service accounts across the instance."""
    conditions = () if service_account is None else (User.service_account == service_account,)
    users = await User.find(*conditions, order_by=col(User.email))
    memberships = await OrgMembership.find(order_by=col(OrgMembership.org_id))
    orgs_by_user: dict[UUID, list[UUID]] = {}
    for membership in memberships:
        orgs_by_user.setdefault(membership.user_id, []).append(membership.org_id)
    return Envelope(data=[_user_out(user, orgs_by_user.get(user.id, [])) for user in users])


@router.put("/users/{user_id}/instance-role", tags=["Instance Users"], dependencies=[require("api", instance_scope, Permission.principals_manage)])
async def change_instance_role(user_id: UUID, body: InstanceRoleIn) -> Envelope[UserOut]:
    user = await User.change_instance_role(user_id, body.instance_role)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    memberships = await OrgMembership.find(OrgMembership.user_id == user_id, order_by=col(OrgMembership.org_id))
    return Envelope(data=_user_out(user, [membership.org_id for membership in memberships]))
