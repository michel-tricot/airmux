from __future__ import annotations

from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import col

from control_plane.authz import Permission, WorkspaceRole
from control_plane.deps import AuthorityDep, OrgDep, WorkspaceDep, org_target, require, workspace_target
from control_plane.keys import mint_inference_key
from control_plane.models import InferenceKey, Org, OrgMembership, User, Workspace, WorkspaceMembership
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.inference_key import InferenceKeyIn, InferenceKeyMintedOut, InferenceKeyOut, InferenceKeyRevokedOut
from control_plane.models.workspace import WorkspaceCreate, WorkspaceOut, WorkspaceUpdate
from control_plane.models.workspace_membership import WorkspaceMembershipIn, WorkspaceMembershipOut
from control_plane.routes.provider_credentials import secret_store

router = APIRouter(prefix="/org/workspaces")


@router.post("", tags=["Workspaces"], dependencies=[require(Permission.workspaces_create, org_target)])
async def create_workspace(body: WorkspaceCreate, org_id: OrgDep, authority: AuthorityDep) -> Envelope[WorkspaceOut]:
    """The creator becomes the first member when they hold an org membership; an instance owner
    acting on an org they never joined creates it member-less and relies on their bypass.

    A caller who names no slug gets one derived from the name; one who does gets a 409 when the
    org already holds it, rather than a silently numbered variant of what they asked for."""
    if await Org.find_by_id(org_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if body.slug and await Workspace.slug_taken(org_id, body.slug):
        raise HTTPException(status_code=409, detail="slug is already taken in this org")
    slug = body.slug or await Workspace.free_slug(org_id, body.name)
    workspace = await Workspace(org_id=org_id, name=body.name, slug=slug).save()
    if await OrgMembership.get((authority.principal_id, org_id)) is not None:
        await WorkspaceMembership(user_id=authority.principal_id, workspace_id=workspace.id, org_id=org_id, role=WorkspaceRole.admin).save()
    return Envelope(data=WorkspaceOut.model_validate(workspace))


@router.get("", tags=["Workspaces"], dependencies=[require(Permission.workspaces_read, org_target)])
async def list_workspaces(org_id: OrgDep) -> Envelope[list[WorkspaceOut]]:
    workspaces = await Workspace.find(Workspace.org_id == org_id, order_by=col(Workspace.name))
    return Envelope(data=[WorkspaceOut.model_validate(w) for w in workspaces])


@router.get("/{workspace_ref}", tags=["Workspaces"], dependencies=[require(Permission.workspaces_read, workspace_target)])
async def get_workspace(workspace: WorkspaceDep) -> Envelope[WorkspaceOut]:
    return Envelope(data=WorkspaceOut.model_validate(workspace))


@router.delete("/{workspace_ref}", tags=["Workspaces"], dependencies=[require(Permission.workspaces_delete, workspace_target)])
async def delete_workspace(workspace: WorkspaceDep, request: Request) -> Envelope[DeletedOut[UUID]]:
    """Delete a workspace with its inference keys, its members, and the provider credentials it brought;
    the usage it recorded stays, as it does for an org."""
    await workspace.delete_with_contents(secret_store(request))
    return Envelope(data=DeletedOut.of(workspace.id))


@router.patch("/{workspace_ref}", tags=["Workspaces"], dependencies=[require(Permission.workspaces_update, workspace_target)])
async def update_workspace(body: WorkspaceUpdate, workspace: WorkspaceDep) -> Envelope[WorkspaceOut]:
    return Envelope(data=WorkspaceOut.model_validate(await workspace.apply(body).save()))


@router.get("/{workspace_ref}/members", tags=["Workspaces"], dependencies=[require(Permission.members_read, workspace_target)])
async def list_members(workspace: WorkspaceDep) -> Envelope[list[WorkspaceMembershipOut]]:
    memberships = await WorkspaceMembership.find(WorkspaceMembership.workspace_id == workspace.id, order_by=col(WorkspaceMembership.user_id))
    return Envelope(
        data=[
            WorkspaceMembershipOut(user_id=membership.user_id, workspace_id=workspace.id, role=membership.role, status="member")
            for membership in memberships
        ]
    )


@router.put("/{workspace_ref}/members/{user_id}", tags=["Workspaces"], dependencies=[require(Permission.members_manage, workspace_target)])
async def add_member(user_id: UUID, body: WorkspaceMembershipIn, workspace: WorkspaceDep) -> Envelope[WorkspaceMembershipOut]:
    """The composite foreign keys are the enforcement; the 409 turns what they would reject into a client error."""
    if await User.find_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if await OrgMembership.get((user_id, workspace.org_id)) is None:
        raise HTTPException(status_code=409, detail="user is not a member of the org")
    membership = await WorkspaceMembership.get((user_id, workspace.id))
    if membership is None:
        membership = WorkspaceMembership(user_id=user_id, workspace_id=workspace.id, org_id=workspace.org_id, role=body.role)
    else:
        membership.role = body.role
    await membership.save()
    return Envelope(data=WorkspaceMembershipOut(user_id=user_id, workspace_id=workspace.id, role=membership.role, status="member"))


@router.delete("/{workspace_ref}/members/{user_id}", tags=["Workspaces"], dependencies=[require(Permission.members_manage, workspace_target)])
async def remove_member(user_id: UUID, workspace: WorkspaceDep) -> Envelope[DeletedOut[str]]:
    membership = await WorkspaceMembership.get((user_id, workspace.id))
    if membership is None:
        raise HTTPException(status_code=404, detail="User is not a member of this workspace")
    await membership.delete()
    return Envelope(data=DeletedOut.of(f"{user_id}/{workspace.id}"))


@router.post("/{workspace_ref}/inference-keys", tags=["Inference Keys"], dependencies=[require(Permission.inference_keys_manage, workspace_target)])
async def create_inference_key(body: InferenceKeyIn, workspace: WorkspaceDep, authority: AuthorityDep) -> Envelope[InferenceKeyMintedOut]:
    key_id, token = await mint_inference_key(workspace.org_id, workspace.id, authority.principal_id, label=body.label)
    return Envelope(data=InferenceKeyMintedOut(id=key_id, token=token))


@router.get("/{workspace_ref}/inference-keys", tags=["Inference Keys"], dependencies=[require(Permission.inference_keys_read, workspace_target)])
async def list_inference_keys(workspace: WorkspaceDep) -> Envelope[list[InferenceKeyOut]]:
    keys = await InferenceKey.find(InferenceKey.workspace_id == workspace.id, order_by=col(InferenceKey.id))
    return Envelope(data=[InferenceKeyOut.model_validate(k) for k in keys])


@router.delete(
    "/{workspace_ref}/inference-keys/{key_id}", tags=["Inference Keys"], dependencies=[require(Permission.inference_keys_manage, workspace_target)]
)
async def revoke_inference_key(workspace: WorkspaceDep, key_id: UUID) -> Envelope[InferenceKeyRevokedOut]:
    key = await InferenceKey.owned_by(workspace.org_id, key_id)
    if key.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Inference key not found in this workspace")
    key.revoked = True
    await key.save()
    return Envelope(data=InferenceKeyRevokedOut(id=key_id, status="revoked"))
