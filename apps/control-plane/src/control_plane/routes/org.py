from __future__ import annotations

from typing import Annotated
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col

from control_plane.authority import ensure_org_role_change
from control_plane.authz import OrgRole, Permission, Scope
from control_plane.deps import ActorDep, OrgDep, WorkspaceDep, org_scope, require, require_all, workspace_scope
from control_plane.models import AuditLog, Bundle, OrgMembership, RuntimeConfiguration, UsageEvent, User
from control_plane.models.audit import ActivityOut
from control_plane.models.bundle import BundleOut
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.management_key import ManagementKeyCreatedOut, ManagementKeyIn  # noqa: TC001 FastAPI resolves route annotations at runtime
from control_plane.models.org_membership import MembershipOut, OrgMemberOut, OrgMembershipIn
from control_plane.models.runtime_configuration import BundlePublicationStatusOut, BundleRepublishOut
from control_plane.models.usage_event import UsageEventOut, UsageEventPage
from control_plane.models.user import OrgServiceAccountCreatedOut, OrgServiceAccountIn, UserOut
from control_plane.routes.management_keys import issue_management_key

router = APIRouter(prefix="/organizations/{org_id}")


@router.get("/users", tags=["Organization Members"], dependencies=[require("api", org_scope, Permission.members_read)])
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
                managed=user.managing_org_id == org_id,
            )
            for user in members
        ]
    )


@router.put("/users/{user_id}", tags=["Organization Members"], dependencies=[require("api", org_scope, Permission.members_manage)])
async def add_org_user(user_id: UUID, body: OrgMembershipIn, org_id: OrgDep, actor: ActorDep) -> Envelope[MembershipOut]:
    """Add a principal to an organization or update its organization role."""
    user = await User.find_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.managing_org_id is not None and user.managing_org_id != org_id:
        raise HTTPException(status_code=409, detail="Organization-managed service accounts cannot join another organization")
    if user.managing_org_id is not None and body.role is OrgRole.owner:
        raise HTTPException(status_code=409, detail="Organization-managed service accounts cannot own an organization")
    membership = await OrgMembership.get((user_id, org_id))
    current = membership.role if membership else None
    await ensure_org_role_change(actor, org_id, current, body.role)
    if membership is None:
        membership = OrgMembership(user_id=user_id, org_id=org_id, role=body.role)
        await membership.save()
    elif membership.role != body.role:
        await membership.change_role(body.role)
    return Envelope(data=MembershipOut(user_id=user_id, org_id=org_id, role=membership.role, status="member"))


@router.delete("/users/{user_id}", tags=["Organization Members"], dependencies=[require("api", org_scope, Permission.members_manage)])
async def remove_org_user(user_id: UUID, org_id: OrgDep, actor: ActorDep) -> Envelope[DeletedOut[str]]:
    """Remove a principal from an organization and its workspaces."""
    membership = await OrgMembership.get((user_id, org_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="User is not a member of this org")
    user = await User.find_by_id(user_id)
    if user is not None and user.managing_org_id == org_id:
        raise HTTPException(status_code=409, detail="Delete an organization-managed service account instead of removing its membership")
    await ensure_org_role_change(actor, org_id, membership.role, OrgRole.member)
    await membership.delete()
    return Envelope(data=DeletedOut.of(f"{user_id}/{org_id}"))


@router.post(
    "/service-accounts",
    tags=["Organization Service Accounts"],
    dependencies=[require_all("api", org_scope, Permission.members_manage, Permission.management_keys_issue)],
)
async def create_org_service_account(
    body: OrgServiceAccountIn,
    org_id: OrgDep,
    actor: ActorDep,
) -> Envelope[OrgServiceAccountCreatedOut]:
    """Create an organization-managed service account and its first management key."""
    await ensure_org_role_change(actor, org_id, None, OrgRole.admin)
    service_account = await User.new_service_account(body.name, managing_org_id=org_id).save()
    membership = await OrgMembership(user_id=service_account.id, org_id=org_id, role=OrgRole.admin).save()
    management_key = await issue_management_key(
        body.management_key,
        actor,
        Scope.org(org_id),
        principal_id=service_account.id,
    )
    return Envelope(
        data=OrgServiceAccountCreatedOut(
            service_account=UserOut.model_validate({**service_account.model_dump(), "orgs": [org_id]}),
            membership=MembershipOut(user_id=service_account.id, org_id=org_id, role=OrgRole(membership.role), status="member"),
            management_key=management_key,
        )
    )


@router.post(
    "/service-accounts/{user_id}/management-keys",
    tags=["Organization Service Accounts"],
    dependencies=[require("api", org_scope, Permission.management_keys_issue)],
)
async def create_org_service_account_management_key(
    user_id: UUID,
    body: ManagementKeyIn,
    org_id: OrgDep,
    actor: ActorDep,
) -> Envelope[ManagementKeyCreatedOut]:
    """Issue a replacement key for an organization-managed service account."""
    service_account = await User.owned_by(org_id, user_id)
    return Envelope(data=await issue_management_key(body, actor, Scope.org(org_id), principal_id=service_account.id))


@router.delete(
    "/service-accounts/{user_id}",
    tags=["Organization Service Accounts"],
    dependencies=[require_all("api", org_scope, Permission.members_manage, Permission.management_keys_revoke)],
)
async def delete_org_service_account(user_id: UUID, org_id: OrgDep, actor: ActorDep) -> Envelope[DeletedOut[UUID]]:
    """Delete an organization-managed service account and its control-plane credentials."""
    service_account = await User.owned_by(org_id, user_id)
    membership = await OrgMembership.get((user_id, org_id))
    if membership is not None:
        await ensure_org_role_change(actor, org_id, membership.role, OrgRole.member)
    if membership is not None:
        await membership.delete()
    await service_account.delete_with_contents()
    return Envelope(data=DeletedOut.of(user_id))


@router.post(
    "/bundles/republish",
    tags=["Organization Bundles"],
    dependencies=[require("api", org_scope, Permission.bundles_publish)],
    status_code=202,
)
async def republish_bundle(org_id: OrgDep) -> Envelope[BundleRepublishOut]:
    """Queue a fresh bundle for the organization's current configuration."""
    revision = await RuntimeConfiguration.request_republication(org_id)
    return Envelope(data=BundleRepublishOut(queued_revision=revision, publication=await RuntimeConfiguration.status(org_id)))


@router.get("/bundles/status", tags=["Organization Bundles"], dependencies=[require("api", org_scope, Permission.bundles_read)])
async def get_bundle_publication_status(org_id: OrgDep) -> Envelope[BundlePublicationStatusOut]:
    """Return the organization's control-plane bundle publication state."""
    return Envelope(data=await RuntimeConfiguration.status(org_id))


@router.get("/bundles", tags=["Organization Bundles"], dependencies=[require("api", org_scope, Permission.bundles_read)])
async def list_bundles(org_id: OrgDep) -> Envelope[list[BundleOut]]:
    """List policy bundle metadata for an organization."""
    bundles = await Bundle.find(Bundle.org_id == org_id, order_by=col(Bundle.version))
    return Envelope(data=[BundleOut.model_validate(bundle) for bundle in bundles])


@router.get("/events", tags=["Organization Usage Events"], dependencies=[require("api", org_scope, Permission.usage_read)])
async def list_org_events(org_id: OrgDep, page: Annotated[UsageEventPage, Query()]) -> Envelope[list[UsageEventOut]]:
    """List usage events across an organization with cursor pagination."""
    events = await UsageEvent.for_scope(org_id, None, page)
    return Envelope(data=[UsageEventOut.model_validate(event) for event in events])


@router.get(
    "/workspaces/{workspace_ref}/events", tags=["Workspace Usage Events"], dependencies=[require("api", workspace_scope, Permission.usage_read)]
)
async def list_workspace_events(workspace: WorkspaceDep, page: Annotated[UsageEventPage, Query()]) -> Envelope[list[UsageEventOut]]:
    """List usage events for one workspace with cursor pagination."""
    events = await UsageEvent.for_scope(workspace.org_id, workspace.id, page)
    return Envelope(data=[UsageEventOut.model_validate(event) for event in events])


@router.get("/activity", tags=["Organization Activity"], dependencies=[require("api", org_scope, Permission.audit_read)])
async def list_activity(org_id: OrgDep, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Envelope[list[ActivityOut]]:
    """List the most recent audited changes in an organization."""
    return Envelope(data=[ActivityOut.model_validate(entry) for entry in await AuditLog.for_org(org_id, limit)])
