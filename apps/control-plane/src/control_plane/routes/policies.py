from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID  # noqa: TC003 FastAPI resolves path parameter annotations at runtime

from fastapi import APIRouter, Query

from control_plane.authz import Permission
from control_plane.deps import WorkspaceDep, require, require_all, workspace_scope
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.policy import Policy, PolicyBudgetStatus, PolicyCreate, PolicyOrder, PolicyOut, PolicyUpdate
from control_plane.models.usage_event import BudgetUsagePage  # noqa: TC001 FastAPI resolves query annotations at runtime

router = APIRouter(prefix="/organizations/{org_id}/workspaces/{workspace_ref}/policies", tags=["Workspace Policies"])


@router.get("", dependencies=[require("api", workspace_scope, Permission.policies_read)])
async def list_policies(workspace: WorkspaceDep) -> Envelope[list[PolicyOut]]:
    """List workspace inference policies in evaluation order."""
    return Envelope(data=[PolicyOut.model_validate(policy) for policy in await Policy.for_workspace(workspace.id)])


@router.post("", dependencies=[require("api", workspace_scope, Permission.policies_manage)])
async def create_policy(workspace: WorkspaceDep, body: PolicyCreate) -> Envelope[PolicyOut]:
    """Create a workspace inference policy."""
    policy = Policy(
        org_id=workspace.org_id, workspace_id=workspace.id, name=body.name, enabled=body.enabled, priority=body.priority, definition=body.definition
    )
    await policy.save()
    return Envelope(data=PolicyOut.model_validate(policy))


@router.put("/order", dependencies=[require("api", workspace_scope, Permission.policies_manage)])
async def reorder_policies(workspace: WorkspaceDep, body: PolicyOrder) -> Envelope[list[PolicyOut]]:
    """Replace the workspace policy evaluation order."""
    policies = await Policy.reorder(workspace.org_id, workspace.id, body.policy_ids)
    return Envelope(data=[PolicyOut.model_validate(policy) for policy in policies])


@router.patch("/{policy_id}", dependencies=[require("api", workspace_scope, Permission.policies_manage)])
async def update_policy(workspace: WorkspaceDep, policy_id: UUID, body: PolicyUpdate) -> Envelope[PolicyOut]:
    """Update a policy without changing its workspace."""
    policy = await Policy.in_workspace(workspace.org_id, workspace.id, policy_id)
    if body.name is not None:
        policy.name = body.name
    if body.enabled is not None:
        policy.enabled = body.enabled
    if body.priority is not None:
        policy.priority = body.priority
    if body.definition is not None:
        policy.definition = body.definition
    await policy.save()
    return Envelope(data=PolicyOut.model_validate(policy))


@router.delete("/{policy_id}", dependencies=[require("api", workspace_scope, Permission.policies_manage)])
async def delete_policy(workspace: WorkspaceDep, policy_id: UUID) -> Envelope[DeletedOut[UUID]]:
    """Delete a workspace policy and publish the new configuration."""
    policy = await Policy.in_workspace(workspace.org_id, workspace.id, policy_id)
    await policy.delete()
    return Envelope(data=DeletedOut.of(policy.id))


@router.get("/{policy_id}/status", dependencies=[require_all("api", workspace_scope, Permission.policies_read, Permission.usage_read)])
async def policy_status(workspace: WorkspaceDep, policy_id: UUID, page: Annotated[BudgetUsagePage, Query()]) -> Envelope[PolicyBudgetStatus]:
    policy = await Policy.in_workspace(workspace.org_id, workspace.id, policy_id)
    return Envelope(data=await policy.budget_status(datetime.now(UTC), page))
