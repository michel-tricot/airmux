from __future__ import annotations

from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import col

from control_plane.authz import Scope
from control_plane.deps import MgmtDep, OrgDep, WorkspaceDep, require
from control_plane.keys import mint_inference_key
from control_plane.models import InferenceKey, Org, OrgMembership, User, Workspace, WorkspaceMembership
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.inference_key import InferenceKeyIn, InferenceKeyMintedOut, InferenceKeyOut, InferenceKeyRevokedOut
from control_plane.models.workspace import WorkspaceCreate, WorkspaceOut, WorkspaceUpdate
from control_plane.models.workspace_membership import WorkspaceMembershipOut
from control_plane.routes.provider_credentials import secret_store

router = APIRouter(prefix="/org/workspaces")


@router.post("", tags=["Workspaces"], dependencies=[require(Scope.workspaces_create)])
async def create_workspace(body: WorkspaceCreate, org_id: OrgDep, claims: MgmtDep) -> Envelope[WorkspaceOut]:
    """The creator becomes the first member when they hold an org membership; an instance admin
    acting on an org they never joined creates it member-less and relies on their bypass.

    A caller who names no slug gets one derived from the name; one who does gets a 409 when the
    org already holds it, rather than a silently numbered variant of what they asked for."""
    if await Org.find_by_id(org_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if body.slug and await Workspace.slug_taken(org_id, body.slug):
        raise HTTPException(status_code=409, detail="slug is already taken in this org")
    slug = body.slug or await Workspace.free_slug(org_id, body.name)
    workspace = await Workspace(org_id=org_id, name=body.name, slug=slug).save()
    if await OrgMembership.get((claims.user_id, org_id)) is not None:
        await WorkspaceMembership(user_id=claims.user_id, workspace_id=workspace.id, org_id=org_id).save()
    return Envelope(data=WorkspaceOut.model_validate(workspace))


@router.get("", tags=["Workspaces"], dependencies=[require(Scope.workspaces_read)])
async def list_workspaces(org_id: OrgDep) -> Envelope[list[WorkspaceOut]]:
    workspaces = await Workspace.find(Workspace.org_id == org_id, order_by=col(Workspace.name))
    return Envelope(data=[WorkspaceOut.model_validate(w) for w in workspaces])


@router.get("/{workspace_ref}", tags=["Workspaces"], dependencies=[require(Scope.workspaces_read)])
async def get_workspace(workspace_ref: str, org_id: OrgDep) -> Envelope[WorkspaceOut]:
    return Envelope(data=WorkspaceOut.model_validate(await Workspace.by_ref(org_id, workspace_ref)))


@router.delete("/{workspace_ref}", tags=["Workspaces"], dependencies=[require(Scope.workspaces_delete)])
async def delete_workspace(workspace_ref: str, org_id: OrgDep, request: Request) -> Envelope[DeletedOut[UUID]]:
    """Delete a workspace with its inference keys, its members, and the provider credentials it brought;
    the usage it recorded stays, as it does for an org."""
    workspace = await Workspace.by_ref(org_id, workspace_ref)
    await workspace.delete_with_contents(secret_store(request))
    return Envelope(data=DeletedOut.of(workspace.id))


@router.patch("/{workspace_ref}", tags=["Workspaces"], dependencies=[require(Scope.workspaces_write)])
async def update_workspace(workspace_ref: str, body: WorkspaceUpdate, org_id: OrgDep) -> Envelope[WorkspaceOut]:
    workspace = await Workspace.by_ref(org_id, workspace_ref)
    return Envelope(data=WorkspaceOut.model_validate(await workspace.apply(body).save()))


@router.get("/{workspace_ref}/members", tags=["Workspaces"], dependencies=[require(Scope.workspaces_read)])
async def list_members(workspace_ref: str, org_id: OrgDep) -> Envelope[list[WorkspaceMembershipOut]]:
    workspace = await Workspace.by_ref(org_id, workspace_ref)
    memberships = await WorkspaceMembership.find(WorkspaceMembership.workspace_id == workspace.id, order_by=col(WorkspaceMembership.user_id))
    return Envelope(data=[WorkspaceMembershipOut(user_id=m.user_id, workspace_id=workspace.id, status="member") for m in memberships])


@router.put("/{workspace_ref}/members/{user_id}", tags=["Workspaces"], dependencies=[require(Scope.workspaces_write)])
async def add_member(workspace_ref: str, user_id: UUID, org_id: OrgDep) -> Envelope[WorkspaceMembershipOut]:
    """The composite foreign keys are the enforcement; the 409 turns what they would reject into a client error."""
    workspace = await Workspace.by_ref(org_id, workspace_ref)
    if await User.find_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if await OrgMembership.get((user_id, org_id)) is None:
        raise HTTPException(status_code=409, detail="user is not a member of the org")
    if await WorkspaceMembership.get((user_id, workspace.id)) is None:
        await WorkspaceMembership(user_id=user_id, workspace_id=workspace.id, org_id=org_id).save()
    return Envelope(data=WorkspaceMembershipOut(user_id=user_id, workspace_id=workspace.id, status="member"))


@router.delete("/{workspace_ref}/members/{user_id}", tags=["Workspaces"], dependencies=[require(Scope.workspaces_write)])
async def remove_member(workspace_ref: str, user_id: UUID, org_id: OrgDep) -> Envelope[DeletedOut[str]]:
    workspace = await Workspace.by_ref(org_id, workspace_ref)
    membership = await WorkspaceMembership.get((user_id, workspace.id))
    if membership is None:
        raise HTTPException(status_code=404, detail="User is not a member of this workspace")
    await membership.delete()
    return Envelope(data=DeletedOut.of(f"{user_id}/{workspace.id}"))


@router.post("/{workspace_ref}/inference-keys", tags=["Inference Keys"], dependencies=[require(Scope.inference_keys_write)])
async def create_inference_key(body: InferenceKeyIn, workspace: WorkspaceDep, claims: MgmtDep) -> Envelope[InferenceKeyMintedOut]:
    key_id, token = await mint_inference_key(workspace.org_id, workspace.id, claims.user_id, label=body.label)
    return Envelope(data=InferenceKeyMintedOut(id=key_id, token=token))


@router.get("/{workspace_ref}/inference-keys", tags=["Inference Keys"], dependencies=[require(Scope.inference_keys_read)])
async def list_inference_keys(workspace: WorkspaceDep) -> Envelope[list[InferenceKeyOut]]:
    keys = await InferenceKey.find(InferenceKey.workspace_id == workspace.id, order_by=col(InferenceKey.id))
    return Envelope(data=[InferenceKeyOut.model_validate(k) for k in keys])


@router.delete("/{workspace_ref}/inference-keys/{key_id}", tags=["Inference Keys"], dependencies=[require(Scope.inference_keys_write)])
async def revoke_inference_key(workspace: WorkspaceDep, key_id: UUID) -> Envelope[InferenceKeyRevokedOut]:
    key = await InferenceKey.owned_by(workspace.org_id, key_id)
    if key.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Inference key not found in this workspace")
    key.revoked = True
    await key.save()
    return Envelope(data=InferenceKeyRevokedOut(id=key_id, status="revoked"))
