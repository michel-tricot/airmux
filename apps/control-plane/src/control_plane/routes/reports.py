from __future__ import annotations

from typing import Annotated
from uuid import UUID  # noqa: TC003 FastAPI resolves request_id annotations at runtime

from fastapi import APIRouter, Query

from control_plane.authz import Permission
from control_plane.deps import OrgDep, WorkspaceDep, org_scope, require, workspace_scope
from control_plane.models import GatewayRequest, NotOwnedError
from control_plane.models.common.wire import Envelope
from control_plane.models.overview_report import (  # noqa: TC001 FastAPI resolves route annotations at runtime
    OverviewReportOut,
    OverviewReportQuery,
    WorkspaceOverviewReportQuery,
)
from control_plane.models.request_report import (  # noqa: TC001 FastAPI resolves route annotations at runtime
    GatewayRequestCsvExportOut,
    GatewayRequestDetailOut,
    GatewayRequestPageOut,
    OrgRequestExportQuery,
    OrgRequestReportQuery,
    RequestAsOfQuery,
    WorkspaceRequestExportQuery,
    WorkspaceRequestReportQuery,
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


@router.get("/reports/requests", tags=["Organization Reporting"], dependencies=[require("api", org_scope, Permission.usage_read)])
async def list_org_gateway_requests(
    org_id: OrgDep,
    query: Annotated[OrgRequestReportQuery, Query()],
) -> Envelope[GatewayRequestPageOut]:
    """List logical requests and their visible provider-attempt evidence for an organization."""
    return Envelope(data=await GatewayRequest.request_page(org_id, None, query))


@router.get(
    "/workspaces/{workspace_ref}/reports/requests",
    tags=["Workspace Reporting"],
    dependencies=[require("api", workspace_scope, Permission.usage_read)],
)
async def list_workspace_gateway_requests(
    workspace: WorkspaceDep,
    query: Annotated[WorkspaceRequestReportQuery, Query()],
) -> Envelope[GatewayRequestPageOut]:
    """List logical requests and their visible provider-attempt evidence for one workspace."""
    return Envelope(data=await GatewayRequest.request_page(workspace.org_id, workspace.id, query))


@router.get(
    "/reports/request-export",
    tags=["Organization Reporting"],
    dependencies=[require("api", org_scope, Permission.usage_read)],
)
async def export_org_gateway_requests(
    org_id: OrgDep,
    query: Annotated[OrgRequestExportQuery, Query()],
) -> Envelope[GatewayRequestCsvExportOut]:
    """Export every matching logical request as one CSV row at one ingestion watermark."""
    return Envelope(data=await GatewayRequest.request_export(org_id, None, query))


@router.get(
    "/workspaces/{workspace_ref}/reports/request-export",
    tags=["Workspace Reporting"],
    dependencies=[require("api", workspace_scope, Permission.usage_read)],
)
async def export_workspace_gateway_requests(
    workspace: WorkspaceDep,
    query: Annotated[WorkspaceRequestExportQuery, Query()],
) -> Envelope[GatewayRequestCsvExportOut]:
    """Export every matching logical request in one workspace as one CSV row at one ingestion watermark."""
    return Envelope(data=await GatewayRequest.request_export(workspace.org_id, workspace.id, query))


@router.get(
    "/reports/requests/{request_id}",
    tags=["Organization Reporting"],
    dependencies=[require("api", org_scope, Permission.usage_read)],
)
async def get_org_gateway_request(
    request_id: UUID,
    org_id: OrgDep,
    query: Annotated[RequestAsOfQuery, Query()],
) -> Envelope[GatewayRequestDetailOut]:
    """Get one logical request and all of its visible provider-attempt evidence."""
    detail = await GatewayRequest.request_detail(org_id, None, request_id, query)
    if detail is None:
        raise NotOwnedError
    return Envelope(data=detail)


@router.get(
    "/workspaces/{workspace_ref}/reports/requests/{request_id}",
    tags=["Workspace Reporting"],
    dependencies=[require("api", workspace_scope, Permission.usage_read)],
)
async def get_workspace_gateway_request(
    request_id: UUID,
    workspace: WorkspaceDep,
    query: Annotated[RequestAsOfQuery, Query()],
) -> Envelope[GatewayRequestDetailOut]:
    """Get one logical request and all of its visible provider-attempt evidence for one workspace."""
    detail = await GatewayRequest.request_detail(workspace.org_id, workspace.id, request_id, query)
    if detail is None:
        raise NotOwnedError
    return Envelope(data=detail)
