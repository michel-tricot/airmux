from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, HTTPException
from sqlmodel import col

from control_plane.authz import Scope
from control_plane.deps import MgmtDep, OrgDep, WorkspaceDep, require
from control_plane.keys import mint_inference_key
from control_plane.models import InferenceKey, Org, OrgMembership, User, Workspace, WorkspaceMembership
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.inference_key import InferenceKeyIn, InferenceKeyMintedOut, InferenceKeyOut, InferenceKeyRevokedOut
from control_plane.models.workspace import WorkspaceCreate, WorkspaceOut, WorkspaceUpdate
from control_plane.models.workspace_membership import WorkspaceMembershipOut

router = APIRouter(prefix="/org/workspaces")


@router.post("", tags=["Workspaces"], dependencies=[require(Scope.workspaces_write)])
async def create_workspace(body: WorkspaceCreate, org_id: OrgDep, claims: MgmtDep) -> Envelope[WorkspaceOut]:
    """The creator becomes the first member when they hold an org membership; an instance admin
    acting on an org they never joined creates it member-less and relies on their bypass."""
    if await Org.find_by_id(org_id) is None:
        raise HTTPException(status_code=404)
    workspace = await Workspace(org_id=org_id, name=body.name).save()
    if await OrgMembership.get((claims.user_id, org_id)) is not None:
        await WorkspaceMembership(user_id=claims.user_id, workspace_id=workspace.id, org_id=org_id).save()
    return Envelope(data=WorkspaceOut.model_validate(workspace))


@router.get("", tags=["Workspaces"], dependencies=[require(Scope.workspaces_read)])
async def list_workspaces(org_id: OrgDep) -> Envelope[list[WorkspaceOut]]:
    workspaces = await Workspace.find(Workspace.org_id == org_id, order_by=col(Workspace.name))
    return Envelope(data=[WorkspaceOut.model_validate(w) for w in workspaces])


@router.patch("/{workspace_id}", tags=["Workspaces"], dependencies=[require(Scope.workspaces_write)])
async def update_workspace(workspace_id: UUID, body: WorkspaceUpdate, org_id: OrgDep) -> Envelope[WorkspaceOut]:
    workspace = await Workspace.owned_by(org_id, workspace_id)
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(workspace, name, value)
    return Envelope(data=WorkspaceOut.model_validate(await workspace.save()))


@router.get("/{workspace_id}/members", tags=["Workspaces"], dependencies=[require(Scope.workspaces_read)])
async def list_members(workspace_id: UUID, org_id: OrgDep) -> Envelope[list[WorkspaceMembershipOut]]:
    await Workspace.owned_by(org_id, workspace_id)
    memberships = await WorkspaceMembership.find(WorkspaceMembership.workspace_id == workspace_id, order_by=col(WorkspaceMembership.user_id))
    return Envelope(data=[WorkspaceMembershipOut(user_id=m.user_id, workspace_id=workspace_id, status="member") for m in memberships])


@router.put("/{workspace_id}/members/{user_id}", tags=["Workspaces"], dependencies=[require(Scope.workspaces_write)])
async def add_member(workspace_id: UUID, user_id: UUID, org_id: OrgDep) -> Envelope[WorkspaceMembershipOut]:
    """The composite foreign keys are the enforcement; the 409 turns what they would reject into a client error."""
    await Workspace.owned_by(org_id, workspace_id)
    if await User.find_by_id(user_id) is None:
        raise HTTPException(status_code=404)
    if await OrgMembership.get((user_id, org_id)) is None:
        raise HTTPException(status_code=409, detail="user is not a member of the org")
    if await WorkspaceMembership.get((user_id, workspace_id)) is None:
        await WorkspaceMembership(user_id=user_id, workspace_id=workspace_id, org_id=org_id).save()
    return Envelope(data=WorkspaceMembershipOut(user_id=user_id, workspace_id=workspace_id, status="member"))


@router.delete("/{workspace_id}/members/{user_id}", tags=["Workspaces"], dependencies=[require(Scope.workspaces_write)])
async def remove_member(workspace_id: UUID, user_id: UUID, org_id: OrgDep) -> Envelope[DeletedOut[str]]:
    await Workspace.owned_by(org_id, workspace_id)
    membership = await WorkspaceMembership.get((user_id, workspace_id))
    if membership is None:
        raise HTTPException(status_code=404)
    await membership.delete()
    return Envelope(data=DeletedOut(id=f"{user_id}/{workspace_id}", deleted_at=datetime.now(tz=UTC)))


@router.post("/{workspace_id}/inference-keys", tags=["Inference Keys"], dependencies=[require(Scope.inference_keys_write)])
async def create_inference_key(body: InferenceKeyIn, workspace: WorkspaceDep, claims: MgmtDep) -> Envelope[InferenceKeyMintedOut]:
    key_id, token = await mint_inference_key(workspace.org_id, workspace.id, claims.user_id, label=body.label)
    return Envelope(data=InferenceKeyMintedOut(id=key_id, token=token))


@router.get("/{workspace_id}/inference-keys", tags=["Inference Keys"], dependencies=[require(Scope.inference_keys_read)])
async def list_inference_keys(workspace: WorkspaceDep) -> Envelope[list[InferenceKeyOut]]:
    keys = await InferenceKey.find(InferenceKey.workspace_id == workspace.id, order_by=col(InferenceKey.id))
    return Envelope(data=[InferenceKeyOut.model_validate(k) for k in keys])


@router.delete("/{workspace_id}/inference-keys/{key_id}", tags=["Inference Keys"], dependencies=[require(Scope.inference_keys_write)])
async def revoke_inference_key(workspace: WorkspaceDep, key_id: UUID) -> Envelope[InferenceKeyRevokedOut]:
    key = await InferenceKey.owned_by(workspace.org_id, key_id)
    if key.workspace_id != workspace.id:
        raise HTTPException(status_code=404)
    key.revoked = True
    return Envelope(data=InferenceKeyRevokedOut(id=key_id, status="revoked"))
