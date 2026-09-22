from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from control_plane.authz import Permission
from control_plane.deps import OrgDep, WorkspaceDep, org_scope, require, workspace_scope
from control_plane.models import GatewayRequest
from control_plane.models.common.wire import Envelope
from control_plane.models.overview_report import (  # noqa: TC001 FastAPI resolves route annotations at runtime
    OverviewReportOut,
    OverviewReportQuery,
    WorkspaceOverviewReportQuery,
)

router = APIRouter(prefix="/organizations/{org_id}")


@router.get("/reports/overview", tags=["Organization Reporting"], dependencies=[require("api", org_scope, Permission.usage_read)])
async def get_org_overview_report(org_id: OrgDep, query: Annotated[OverviewReportQuery, Query()]) -> Envelope[OverviewReportOut]:
    """Report reconciled request, usage, cost, trend, and attribution facts for an organization."""
    return Envelope(data=await GatewayRequest.overview_report(org_id, None, query))


@router.get(
    "/workspaces/{workspace_ref}/reports/overview",
    tags=["Workspace Reporting"],
    dependencies=[require("api", workspace_scope, Permission.usage_read)],
)
async def get_workspace_overview_report(
    workspace: WorkspaceDep,
    query: Annotated[WorkspaceOverviewReportQuery, Query()],
) -> Envelope[OverviewReportOut]:
    """Report reconciled request, usage, cost, trend, and attribution facts for one workspace."""
    return Envelope(data=await GatewayRequest.overview_report(workspace.org_id, workspace.id, query))
