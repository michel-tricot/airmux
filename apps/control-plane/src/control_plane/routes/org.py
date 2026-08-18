from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, HTTPException, Query, Request
from sqlmodel import col

from control_plane.authority import ensure_org_role_change
from control_plane.authz import OrgRole, Permission
from control_plane.compiler import publish_pending
from control_plane.deps import ActorDep, OrgDep, WorkspaceDep, org_scope, require, workspace_scope
from control_plane.models import AuditLog, Bundle, OrgMembership, RuntimeConfiguration, UsageEvent, User
from control_plane.models.audit import ActivityOut
from control_plane.models.bundle import BundleOut
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.org_membership import MembershipOut, OrgMemberOut, OrgMembershipIn
from control_plane.models.usage_event import UsageEventOut, UsageEventPage

router = APIRouter(prefix="/orgs/{org_id}")


@router.get("/users", tags=["Organization Members"], dependencies=[require(org_scope, Permission.members_read)])
async def list_org_users(org_id: OrgDep) -> Envelope[list[OrgMemberOut]]:
    """List the human users and service accounts that belong to an organization."""
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


@router.put("/users/{user_id}", tags=["Organization Members"], dependencies=[require(org_scope, Permission.members_manage)])
async def add_org_user(user_id: UUID, body: OrgMembershipIn, org_id: OrgDep, actor: ActorDep) -> Envelope[MembershipOut]:
    """Add a principal to an organization or update its organization role."""
    if await User.find_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    membership = await OrgMembership.get((user_id, org_id))
    current = membership.role if membership else None
    await ensure_org_role_change(actor, org_id, current, body.role)
    if membership is None:
        membership = OrgMembership(user_id=user_id, org_id=org_id, role=body.role)
    elif membership.role != body.role:
        if await membership.is_only_owner():
            raise HTTPException(status_code=409, detail="An organization must keep at least one owner")
        membership.role = body.role
    await membership.save()
    return Envelope(data=MembershipOut(user_id=user_id, org_id=org_id, role=membership.role, status="member"))


@router.delete("/users/{user_id}", tags=["Organization Members"], dependencies=[require(org_scope, Permission.members_manage)])
async def remove_org_user(user_id: UUID, org_id: OrgDep, actor: ActorDep) -> Envelope[DeletedOut[str]]:
    """Remove a principal from an organization and its workspaces."""
    membership = await OrgMembership.get((user_id, org_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="User is not a member of this org")
    await ensure_org_role_change(actor, org_id, membership.role, OrgRole.member)
    if await membership.is_only_owner():
        raise HTTPException(status_code=409, detail="An organization must keep at least one owner")
    await membership.delete()
    return Envelope(data=DeletedOut.of(f"{user_id}/{org_id}"))


@router.post("/bundles/republish", tags=["Organization Bundles"], dependencies=[require(org_scope, Permission.bundles_publish)])
async def republish_bundle(org_id: OrgDep, request: Request) -> Envelope[BundleOut]:
    """Request a fresh signed bundle for the organization's current configuration."""
    settings = request.app.state.settings
    now = datetime.now(tz=UTC)
    await RuntimeConfiguration.request_republication(org_id)
    published = await publish_pending(now, settings.bundle.staleness_bound, settings.bundle.signing_key)
    bundle = next(bundle for bundle in published if bundle.org_id == org_id)
    return Envelope(data=BundleOut.model_validate(bundle))


@router.get("/bundles", tags=["Organization Bundles"], dependencies=[require(org_scope, Permission.bundles_read)])
async def list_bundles(org_id: OrgDep) -> Envelope[list[BundleOut]]:
    """List policy bundle metadata for an organization."""
    bundles = await Bundle.find(Bundle.org_id == org_id, order_by=col(Bundle.version))
    return Envelope(data=[BundleOut.model_validate(bundle) for bundle in bundles])


@router.get("/events", tags=["Organization Usage Events"], dependencies=[require(org_scope, Permission.usage_read)])
async def list_org_events(org_id: OrgDep, page: Annotated[UsageEventPage, Query()]) -> Envelope[list[UsageEventOut]]:
    """List usage events across an organization with cursor pagination."""
    events = await UsageEvent.for_scope(org_id, None, page)
    return Envelope(data=[UsageEventOut.model_validate(event) for event in events])


@router.get("/workspaces/{workspace_ref}/events", tags=["Workspace Usage Events"], dependencies=[require(workspace_scope, Permission.usage_read)])
async def list_workspace_events(workspace: WorkspaceDep, page: Annotated[UsageEventPage, Query()]) -> Envelope[list[UsageEventOut]]:
    """List usage events for one workspace with cursor pagination."""
    events = await UsageEvent.for_scope(workspace.org_id, workspace.id, page)
    return Envelope(data=[UsageEventOut.model_validate(event) for event in events])


@router.get("/activity", tags=["Organization Activity"], dependencies=[require(org_scope, Permission.audit_read)])
async def list_activity(org_id: OrgDep, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Envelope[list[ActivityOut]]:
    """List the most recent audited changes in an organization."""
    return Envelope(data=[ActivityOut.model_validate(entry) for entry in await AuditLog.for_org(org_id, limit)])
