from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from control_plane.authz import Permission, Scope
from control_plane.deps import OrgDep, require
from control_plane.models import Workspace
from control_plane.models.common.org_owned import NotOwnedError
from control_plane.models.common.wire import Envelope
from control_plane.models.reporting import (
    AttributionQuery,
    AttributionReportOut,
    FilterOptionsOut,
    FilterOptionsQuery,
    ReportQuery,
    RequestDetailOut,
    RequestExportOut,
    RequestPageOut,
    RequestQuery,
    UsageReportOut,
)

router = APIRouter(prefix="/organizations/{org_id}/reports", tags=["Organization Reports"])


async def report_scope(org_id: OrgDep, request: Request) -> Scope:
    workspace_ref = request.query_params.get("workspace_id")
    if workspace_ref is None:
        return Scope.org(org_id)
    try:
        workspace_id = UUID(workspace_ref)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Invalid workspace_id") from error
    try:
        await Workspace.owned_by(org_id, workspace_id)
    except NotOwnedError:
        if await Workspace.find_by_id(workspace_id) is not None:
            raise
        return Scope.org(org_id)
    return Scope.workspace(org_id, workspace_id)


report_access = require("api", report_scope, Permission.usage_read)


@router.get("/usage", dependencies=[report_access])
async def get_usage_report(org_id: OrgDep, query: Annotated[ReportQuery, Query()]) -> Envelope[UsageReportOut]:
    return Envelope(data=await UsageReportOut.for_scope(org_id, query, datetime.now(UTC)))


@router.get("/attribution", dependencies=[report_access])
async def get_attribution_report(org_id: OrgDep, query: Annotated[AttributionQuery, Query()]) -> Envelope[AttributionReportOut]:
    return Envelope(data=await AttributionReportOut.for_scope(org_id, query, datetime.now(UTC)))


@router.get("/filter-options", dependencies=[report_access])
async def get_report_filter_options(org_id: OrgDep, query: Annotated[FilterOptionsQuery, Query()]) -> Envelope[FilterOptionsOut]:
    return Envelope(data=await FilterOptionsOut.for_scope(org_id, query, datetime.now(UTC)))


@router.get("/requests", dependencies=[report_access])
async def list_usage_requests(org_id: OrgDep, query: Annotated[RequestQuery, Query()]) -> Envelope[RequestPageOut]:
    return Envelope(data=await RequestPageOut.for_scope(org_id, query, datetime.now(UTC)))


@router.get("/requests/export", dependencies=[report_access])
async def export_usage_requests(org_id: OrgDep, query: Annotated[RequestQuery, Query()]) -> Envelope[RequestExportOut]:
    return Envelope(data=await RequestExportOut.for_scope(org_id, query, datetime.now(UTC)))


@router.get("/requests/{request_id}", dependencies=[report_access])
async def get_usage_request(org_id: OrgDep, request_id: UUID, query: Annotated[ReportQuery, Query()]) -> Envelope[RequestDetailOut]:
    request = await RequestDetailOut.for_scope(org_id, request_id, query, datetime.now(UTC))
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return Envelope(data=request)
