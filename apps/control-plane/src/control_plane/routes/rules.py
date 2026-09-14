from __future__ import annotations

from uuid import UUID  # noqa: TC003 FastAPI resolves path parameter annotations at runtime

from fastapi import APIRouter, HTTPException

from control_plane.authz import Permission
from control_plane.deps import WorkspaceDep, require, workspace_scope
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.rule import InvalidRuleError, Rule, RuleCreate, RuleInUseError, RuleOut, RuleUpdate

router = APIRouter(prefix="/organizations/{org_id}/workspaces/{workspace_ref}/rules", tags=["Workspace Rules"])


@router.get("", dependencies=[require("api", workspace_scope, Permission.policies_read)])
async def list_rules(workspace: WorkspaceDep) -> Envelope[list[RuleOut]]:
    """List reusable inference rules in a workspace."""
    return Envelope(data=[RuleOut.model_validate(rule) for rule in await Rule.for_workspace(workspace.id)])


@router.post("", dependencies=[require("api", workspace_scope, Permission.policies_manage)])
async def create_rule(workspace: WorkspaceDep, body: RuleCreate) -> Envelope[RuleOut]:
    """Create a reusable workspace rule."""
    rule = Rule(org_id=workspace.org_id, workspace_id=workspace.id, name=body.name, definition=body.definition)
    await _save(rule)
    return Envelope(data=RuleOut.model_validate(rule))


@router.patch("/{rule_id}", dependencies=[require("api", workspace_scope, Permission.policies_manage)])
async def update_rule(workspace: WorkspaceDep, rule_id: UUID, body: RuleUpdate) -> Envelope[RuleOut]:
    """Update a rule everywhere it is referenced."""
    rule = await Rule.in_workspace(workspace.org_id, workspace.id, rule_id)
    if body.name is not None:
        rule.name = body.name
    if body.definition is not None:
        rule.definition = body.definition
    await _save(rule)
    return Envelope(data=RuleOut.model_validate(rule))


@router.delete("/{rule_id}", dependencies=[require("api", workspace_scope, Permission.policies_manage)])
async def delete_rule(workspace: WorkspaceDep, rule_id: UUID) -> Envelope[DeletedOut[UUID]]:
    """Delete an unused workspace rule."""
    rule = await Rule.in_workspace(workspace.org_id, workspace.id, rule_id)
    try:
        await rule.delete()
    except RuleInUseError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Envelope(data=DeletedOut.of(rule.id))


async def _save(rule: Rule) -> None:
    try:
        await rule.save()
    except InvalidRuleError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
