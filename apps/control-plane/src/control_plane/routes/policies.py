from __future__ import annotations

from uuid import UUID  # noqa: TC003 FastAPI resolves path parameter annotations at runtime

from fastapi import APIRouter, HTTPException

from control_plane.authz import Permission
from control_plane.deps import WorkspaceDep, require, workspace_scope
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.policy import InvalidPolicyError, Policy, PolicyCreate, PolicyOut, PolicyUpdate

router = APIRouter(prefix="/orgs/{org_id}/workspaces/{workspace_ref}/policies", tags=["Workspace Policies"])


@router.get("", dependencies=[require(workspace_scope, Permission.policies_read)])
async def list_policies(workspace: WorkspaceDep) -> Envelope[list[PolicyOut]]:
    """List workspace inference policies in evaluation order."""
    return Envelope(data=[PolicyOut.model_validate(policy) for policy in await Policy.for_workspace(workspace.id)])


@router.post("", dependencies=[require(workspace_scope, Permission.policies_manage)])
async def create_policy(workspace: WorkspaceDep, body: PolicyCreate) -> Envelope[PolicyOut]:
    """Create a workspace inference policy; budget actions are placeholders only."""
    await workspace.lock_policy_changes()
    policy = Policy(
        org_id=workspace.org_id, workspace_id=workspace.id, name=body.name, enabled=body.enabled, priority=body.priority, definition=body.definition
    )
    await _save(policy)
    return Envelope(data=PolicyOut.model_validate(policy))


@router.patch("/{policy_id}", dependencies=[require(workspace_scope, Permission.policies_manage)])
async def update_policy(workspace: WorkspaceDep, policy_id: UUID, body: PolicyUpdate) -> Envelope[PolicyOut]:
    """Update a policy without changing its workspace."""
    await workspace.lock_policy_changes()
    policy = await Policy.in_workspace(workspace.org_id, workspace.id, policy_id)
    if body.name is not None:
        policy.name = body.name
    if body.enabled is not None:
        policy.enabled = body.enabled
    if body.priority is not None:
        policy.priority = body.priority
    if body.definition is not None:
        policy.definition = body.definition
    await _save(policy)
    return Envelope(data=PolicyOut.model_validate(policy))


@router.delete("/{policy_id}", dependencies=[require(workspace_scope, Permission.policies_manage)])
async def delete_policy(workspace: WorkspaceDep, policy_id: UUID) -> Envelope[DeletedOut[UUID]]:
    """Delete a workspace policy and publish the new configuration."""
    policy = await Policy.in_workspace(workspace.org_id, workspace.id, policy_id)
    await policy.delete()
    return Envelope(data=DeletedOut.of(policy.id))


async def _save(policy: Policy) -> None:
    try:
        await policy.validate_configuration()
    except InvalidPolicyError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    await policy.save()
