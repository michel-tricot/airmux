from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import col

from contract import uuid7
from control_plane.authz import Authority, Boundary, InstanceRole, OrgRole, Permission, Target
from control_plane.compiler import UnknownOrgError, compile_and_store
from control_plane.deps import AuthorityDep, OrgDep, org_target, require
from control_plane.models import AuditLog, Bundle, OrgMembership, UsageEvent, User
from control_plane.models.audit import ActivityOut
from control_plane.models.bundle import BundleOut
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.org_membership import MembershipOut, OrgMemberOut, OrgMembershipIn
from control_plane.models.usage_event import UsageEventOut, UsageEventPage

router = APIRouter(prefix="/org")


@router.get("/users", tags=["Org Users"], dependencies=[require(Permission.members_read, org_target)])
async def list_org_users(org_id: OrgDep) -> Envelope[list[OrgMemberOut]]:
    """The acting org's members; an org credential sees its own roster, never the instance's."""
    members = await User.members_of(org_id)
    memberships = {membership.user_id: membership for membership in await OrgMembership.find(OrgMembership.org_id == org_id)}
    return Envelope(
        data=[
            OrgMemberOut(
                user_id=user.id,
                email=user.email,
                name=user.name,
                service_account=user.service_account,
                role=memberships[user.id].role,
                status="member",
            )
            for user in members
        ]
    )


async def _can_assign_org_role(authority: Authority, org_id: UUID, current: str | None, desired: OrgRole) -> bool:
    actor = await User.find_by_id(authority.principal_id)
    if actor is not None and actor.instance_role == InstanceRole.owner:
        return True
    membership = await OrgMembership.get((authority.principal_id, org_id))
    if membership is None:
        return False
    role = OrgRole(membership.role)
    return role is OrgRole.owner or (role is OrgRole.admin and current != OrgRole.owner and desired is not OrgRole.owner)


async def _last_org_owner(membership: OrgMembership) -> bool:
    if membership.role != OrgRole.owner:
        return False
    owners = await OrgMembership.find(OrgMembership.org_id == membership.org_id, OrgMembership.role == OrgRole.owner)
    return len(owners) == 1


@router.put("/users/{user_id}", tags=["Org Users"], dependencies=[require(Permission.members_manage, org_target)])
async def add_org_user(user_id: UUID, body: OrgMembershipIn, org_id: OrgDep, authority: AuthorityDep) -> Envelope[MembershipOut]:
    """Idempotent: the org comes from the credential, so membership can only ever be granted in scope."""
    if await User.find_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    membership = await OrgMembership.get((user_id, org_id))
    current = membership.role if membership else None
    if not await _can_assign_org_role(authority, org_id, current, body.role):
        raise HTTPException(status_code=403, detail="This role assignment exceeds the acting principal's authority")
    if membership is None:
        membership = OrgMembership(user_id=user_id, org_id=org_id, role=body.role)
    elif membership.role != body.role:
        if await _last_org_owner(membership):
            raise HTTPException(status_code=409, detail="An organization must keep at least one owner")
        membership.role = body.role
    await membership.save()
    return Envelope(data=MembershipOut(user_id=user_id, org_id=org_id, role=membership.role, status="member"))


@router.delete("/users/{user_id}", tags=["Org Users"], dependencies=[require(Permission.members_manage, org_target)])
async def remove_org_user(user_id: UUID, org_id: OrgDep, authority: AuthorityDep) -> Envelope[DeletedOut[str]]:
    """Removing the membership cascades the user out of the org's workspaces."""
    membership = await OrgMembership.get((user_id, org_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="User is not a member of this org")
    if not await _can_assign_org_role(authority, org_id, membership.role, OrgRole.member):
        raise HTTPException(status_code=403, detail="This membership exceeds the acting principal's authority")
    if await _last_org_owner(membership):
        raise HTTPException(status_code=409, detail="An organization must keep at least one owner")
    await membership.delete()
    return Envelope(data=DeletedOut.of(f"{user_id}/{org_id}"))


@router.post("/bundles/compile", tags=["Bundles"], dependencies=[require(Permission.bundles_publish, org_target)])
async def compile_bundle(org_id: OrgDep, request: Request) -> Envelope[BundleOut]:
    settings = request.app.state.settings
    now = datetime.now(tz=UTC)
    try:
        bundle = await compile_and_store(org_id, uuid7(), now, settings.bundle.staleness_bound, settings.bundle.signing_key)
    except UnknownOrgError as e:
        raise HTTPException(status_code=404, detail="Organization not found") from e
    return Envelope(data=BundleOut.model_validate(bundle))


@router.get("/bundles", tags=["Bundles"], dependencies=[require(Permission.bundles_read, org_target)])
async def list_bundles(org_id: OrgDep) -> Envelope[list[BundleOut]]:
    bundles = await Bundle.find(Bundle.org_id == org_id, order_by=col(Bundle.version))
    return Envelope(data=[BundleOut.model_validate(b) for b in bundles])


@dataclass(frozen=True)
class EventSelection:
    org_id: UUID
    page: UsageEventPage
    target: Target


async def event_selection(
    authority: AuthorityDep,
    org_id: OrgDep,
    page: Annotated[UsageEventPage, Query()],
) -> EventSelection:
    workspace_id = authority.workspace_id if authority.boundary is Boundary.workspace and page.workspace_id is None else page.workspace_id
    target = Target.workspace(org_id, workspace_id) if workspace_id is not None else Target.org(org_id)
    return EventSelection(org_id=org_id, page=page.model_copy(update={"workspace_id": target.workspace_id}), target=target)


EventSelectionDep = Annotated[EventSelection, Depends(event_selection)]


async def event_target(selection: EventSelectionDep) -> Target:
    return selection.target


@router.get("/events", tags=["Events"], dependencies=[require(Permission.usage_read, event_target)])
async def list_events(
    selection: EventSelectionDep,
) -> Envelope[list[UsageEventOut]]:
    events = await UsageEvent.for_org(selection.org_id, selection.page)
    return Envelope(data=[UsageEventOut.model_validate(e) for e in events])


@router.get("/activity", tags=["Activity"], dependencies=[require(Permission.audit_read, org_target)])
async def list_activity(org_id: OrgDep, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Envelope[list[ActivityOut]]:
    """What changed in this org, newest first: the audit trail the write triggers already record."""
    return Envelope(data=[ActivityOut.model_validate(entry) for entry in await AuditLog.for_org(org_id, limit)])
