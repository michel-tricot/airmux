from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from control_plane.authz import Permission
from control_plane.deps import OrgDep, WorkspaceDep, org_scope, require, workspace_scope
from control_plane.models.common.wire import Envelope
from control_plane.models.usage_event import RequestPageOut, UsageEvent, UsageReportOut, UsageReportQuery, UsageRequestQuery

router = APIRouter(prefix="/organizations/{org_id}")


@router.get("/reports/usage", tags=["Organization Usage Events"], dependencies=[require("api", org_scope, Permission.usage_read)])
async def get_org_usage_report(org_id: OrgDep, query: Annotated[UsageReportQuery, Query()]) -> Envelope[UsageReportOut]:
    return Envelope(data=await UsageEvent.usage_report(org_id, None, query.days))


@router.get(
    "/workspaces/{workspace_ref}/reports/usage",
    tags=["Workspace Usage Events"],
    dependencies=[require("api", workspace_scope, Permission.usage_read)],
)
async def get_workspace_usage_report(workspace: WorkspaceDep, query: Annotated[UsageReportQuery, Query()]) -> Envelope[UsageReportOut]:
    return Envelope(data=await UsageEvent.usage_report(workspace.org_id, workspace.id, query.days))


@router.get("/reports/requests", tags=["Organization Usage Events"], dependencies=[require("api", org_scope, Permission.usage_read)])
async def list_org_requests(org_id: OrgDep, query: Annotated[UsageRequestQuery, Query()]) -> Envelope[RequestPageOut]:
    return Envelope(data=await UsageEvent.requests(org_id, None, query))


@router.get(
    "/workspaces/{workspace_ref}/reports/requests",
    tags=["Workspace Usage Events"],
    dependencies=[require("api", workspace_scope, Permission.usage_read)],
)
async def list_workspace_requests(workspace: WorkspaceDep, query: Annotated[UsageRequestQuery, Query()]) -> Envelope[RequestPageOut]:
    return Envelope(data=await UsageEvent.requests(workspace.org_id, workspace.id, query))
