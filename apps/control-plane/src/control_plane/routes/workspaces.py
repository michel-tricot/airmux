from __future__ import annotations

from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import col

from control_plane.authority import readable_workspaces
from control_plane.authz import Permission, WorkspaceRole
from control_plane.deps import ActorDep, OrgDep, WorkspaceDep, org_scope, require, require_any, workspace_scope
from control_plane.keys import mint_inference_key
from control_plane.models import InferenceKey, Org, OrgMembership, User, Workspace, WorkspaceMembership
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.inference_key import InferenceKeyIn, InferenceKeyMintedOut, InferenceKeyOut, InferenceKeyRevokedOut
from control_plane.models.workspace import WorkspaceCreate, WorkspaceOut, WorkspaceUpdate
from control_plane.models.workspace_membership import WorkspaceMemberCandidateOut, WorkspaceMembershipIn, WorkspaceMembershipOut
from control_plane.routes.provider_credentials import secret_store

router = APIRouter(prefix="/orgs/{org_id}/workspaces")


@router.post("", tags=["Organization Workspaces"], dependencies=[require(Permission.workspaces_create, org_scope)])
async def create_workspace(body: WorkspaceCreate, org_id: OrgDep, actor: ActorDep) -> Envelope[WorkspaceOut]:
    """Create a workspace and make the creator its first admin when they belong to the organization.

    The slug is derived from the name when omitted and must be unique within the organization.
    """
    if await Org.find_by_id(org_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if body.slug and await Workspace.slug_taken(org_id, body.slug):
        raise HTTPException(status_code=409, detail="slug is already taken in this org")
    slug = body.slug or await Workspace.free_slug(org_id, body.name)
    workspace = await Workspace(org_id=org_id, name=body.name, slug=slug).save()
    if await OrgMembership.get((actor.principal_id, org_id)) is not None:
        await WorkspaceMembership(user_id=actor.principal_id, workspace_id=workspace.id, org_id=org_id, role=WorkspaceRole.admin).save()
    return Envelope(data=WorkspaceOut.model_validate(workspace))


@router.get(
    "",
    tags=["Organization Workspaces"],
    dependencies=[require_any((Permission.workspaces_read, Permission.organizations_read), org_scope)],
)
async def list_workspaces(org_id: OrgDep, actor: ActorDep) -> Envelope[list[WorkspaceOut]]:
    """List workspaces the caller can read in an organization."""
    workspaces = await Workspace.find(Workspace.org_id == org_id, order_by=col(Workspace.name))
    visible = await readable_workspaces(actor, workspaces)
    return Envelope(data=[WorkspaceOut.model_validate(workspace) for workspace in visible])


@router.get("/{workspace_ref}", tags=["Workspace Settings"], dependencies=[require(Permission.workspaces_read, workspace_scope)])
async def get_workspace(workspace: WorkspaceDep) -> Envelope[WorkspaceOut]:
    """Return a workspace by ID or slug."""
    return Envelope(data=WorkspaceOut.model_validate(workspace))


@router.delete("/{workspace_ref}", tags=["Workspace Settings"], dependencies=[require(Permission.workspaces_delete, workspace_scope)])
async def delete_workspace(workspace: WorkspaceDep, request: Request) -> Envelope[DeletedOut[UUID]]:
    """Delete a workspace, its memberships, inference keys, and provider credentials.

    Historical usage events are retained.
    """
    await workspace.delete_with_contents(secret_store(request))
    return Envelope(data=DeletedOut.of(workspace.id))


@router.patch("/{workspace_ref}", tags=["Workspace Settings"], dependencies=[require(Permission.workspaces_update, workspace_scope)])
async def update_workspace(body: WorkspaceUpdate, workspace: WorkspaceDep) -> Envelope[WorkspaceOut]:
    """Update a workspace's name or slug."""
    return Envelope(data=WorkspaceOut.model_validate(await workspace.apply(body).save()))


@router.get("/{workspace_ref}/members", tags=["Workspace Members"], dependencies=[require(Permission.members_read, workspace_scope)])
async def list_members(workspace: WorkspaceDep) -> Envelope[list[WorkspaceMembershipOut]]:
    """List the members of a workspace and their workspace roles."""
    memberships = await WorkspaceMembership.find(WorkspaceMembership.workspace_id == workspace.id, order_by=col(WorkspaceMembership.user_id))
    memberships_by_user = {membership.user_id: membership for membership in memberships}
    users = await User.members_of_workspace(workspace.id)
    return Envelope(
        data=[
            WorkspaceMembershipOut(
                user_id=user.id,
                workspace_id=workspace.id,
                email=user.email,
                name=user.name,
                service_account=user.service_account,
                role=memberships_by_user[user.id].role,
                status="member",
            )
            for user in users
        ]
    )


@router.get(
    "/{workspace_ref}/member-candidates",
    tags=["Workspace Members"],
    dependencies=[require(Permission.members_manage, workspace_scope)],
)
async def list_member_candidates(workspace: WorkspaceDep) -> Envelope[list[WorkspaceMemberCandidateOut]]:
    """List organization members who can be added to a workspace."""
    memberships = await WorkspaceMembership.find(WorkspaceMembership.workspace_id == workspace.id)
    member_ids = frozenset(membership.user_id for membership in memberships)
    candidates = [user for user in await User.members_of(workspace.org_id) if user.id not in member_ids]
    return Envelope(
        data=[
            WorkspaceMemberCandidateOut(user_id=user.id, email=user.email, name=user.name, service_account=user.service_account)
            for user in candidates
        ]
    )


@router.put("/{workspace_ref}/members/{user_id}", tags=["Workspace Members"], dependencies=[require(Permission.members_manage, workspace_scope)])
async def add_member(user_id: UUID, body: WorkspaceMembershipIn, workspace: WorkspaceDep) -> Envelope[WorkspaceMembershipOut]:
    """Add or update a workspace member who already belongs to the organization."""
    user = await User.find_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if await OrgMembership.get((user_id, workspace.org_id)) is None:
        raise HTTPException(status_code=409, detail="user is not a member of the org")
    membership = await WorkspaceMembership.get((user_id, workspace.id))
    if membership is None:
        membership = WorkspaceMembership(user_id=user_id, workspace_id=workspace.id, org_id=workspace.org_id, role=body.role)
    else:
        membership.role = body.role
    await membership.save()
    return Envelope(
        data=WorkspaceMembershipOut(
            user_id=user_id,
            workspace_id=workspace.id,
            email=user.email,
            name=user.name,
            service_account=user.service_account,
            role=membership.role,
            status="member",
        )
    )


@router.delete("/{workspace_ref}/members/{user_id}", tags=["Workspace Members"], dependencies=[require(Permission.members_manage, workspace_scope)])
async def remove_member(user_id: UUID, workspace: WorkspaceDep) -> Envelope[DeletedOut[str]]:
    """Remove a member from a workspace without changing organization membership."""
    membership = await WorkspaceMembership.get((user_id, workspace.id))
    if membership is None:
        raise HTTPException(status_code=404, detail="User is not a member of this workspace")
    await membership.delete()
    return Envelope(data=DeletedOut.of(f"{user_id}/{workspace.id}"))


@router.post(
    "/{workspace_ref}/inference-keys",
    tags=["Workspace Inference Keys"],
    dependencies=[require(Permission.inference_keys_manage, workspace_scope)],
)
async def create_inference_key(body: InferenceKeyIn, workspace: WorkspaceDep, actor: ActorDep) -> Envelope[InferenceKeyMintedOut]:
    """Issue an inference key for model requests to this workspace and return its token once."""
    key_id, token = await mint_inference_key(workspace.org_id, workspace.id, actor.principal_id, label=body.label)
    return Envelope(data=InferenceKeyMintedOut(id=key_id, token=token))


@router.get(
    "/{workspace_ref}/inference-keys",
    tags=["Workspace Inference Keys"],
    dependencies=[require(Permission.inference_keys_read, workspace_scope)],
)
async def list_inference_keys(workspace: WorkspaceDep) -> Envelope[list[InferenceKeyOut]]:
    """List inference-key metadata for a workspace without returning secret tokens."""
    keys = await InferenceKey.find(InferenceKey.workspace_id == workspace.id, order_by=col(InferenceKey.id))
    return Envelope(data=[InferenceKeyOut.model_validate(k) for k in keys])


@router.delete(
    "/{workspace_ref}/inference-keys/{key_id}",
    tags=["Workspace Inference Keys"],
    dependencies=[require(Permission.inference_keys_manage, workspace_scope)],
)
async def revoke_inference_key(workspace: WorkspaceDep, key_id: UUID) -> Envelope[InferenceKeyRevokedOut]:
    """Revoke an inference key in a workspace."""
    key = await InferenceKey.owned_by(workspace.org_id, key_id)
    if key.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Inference key not found in this workspace")
    key.revoked = True
    await key.save()
    return Envelope(data=InferenceKeyRevokedOut(id=key_id, status="revoked"))
