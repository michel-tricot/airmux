from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from sqlmodel import col

from control_plane.authz import Permission
from control_plane.deps import instance_scope, require
from control_plane.models import AuditLog, DataPlaneInstance
from control_plane.models.audit import ActivityOut
from control_plane.models.common.wire import Envelope
from control_plane.models.data_plane_instance import DataPlaneInstanceOut

router = APIRouter(prefix="/instance")


@router.get("/data-planes", tags=["Data Plane"], dependencies=[require(Permission.data_planes_read, instance_scope)])
async def list_data_planes(include_offline: bool = False) -> Envelope[list[DataPlaneInstanceOut]]:
    """List data-plane instances by most recent heartbeat."""
    now = datetime.now(tz=UTC)
    instances = await DataPlaneInstance.find(order_by=col(DataPlaneInstance.last_seen).desc())
    out = [
        DataPlaneInstanceOut(**instance.model_dump(), status=status)
        for instance in instances
        if (status := instance.status(now)) == "online" or include_offline
    ]
    return Envelope(data=out)


@router.get("/activity", tags=["Activity"], dependencies=[require(Permission.audit_read, instance_scope)])
async def list_instance_activity(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Envelope[list[ActivityOut]]:
    """List the most recent audited changes across the instance."""
    return Envelope(data=[ActivityOut.model_validate(entry) for entry in await AuditLog.recent(limit)])
