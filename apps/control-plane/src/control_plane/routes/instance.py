from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlmodel import col

from control_plane.authz import Permission
from control_plane.deps import instance_scope, require
from control_plane.models import AuditLog, DataPlaneInstance
from control_plane.models.audit import ActivityOut
from control_plane.models.common import PageDep  # noqa: TC001 FastAPI resolves route annotations at runtime
from control_plane.models.common.wire import Envelope, PageEnvelope
from control_plane.models.data_plane_instance import DataPlaneInstanceOut

router = APIRouter(prefix="/instance")


@router.get("/data-planes", tags=["Data Plane Instances"], dependencies=[require("api", instance_scope, Permission.data_planes_read)])
async def list_data_planes(include_offline: bool = False) -> Envelope[list[DataPlaneInstanceOut]]:
    """List data-plane instances by most recent heartbeat."""
    now = datetime.now(tz=UTC)
    instances = await DataPlaneInstance.find(order_by=col(DataPlaneInstance.last_seen).desc())
    data = [
        DataPlaneInstanceOut(**instance.model_dump(), status=status)
        for instance in instances
        if (status := instance.status(now)) == "online" or include_offline
    ]
    return Envelope(data=data)


@router.get("/activity", tags=["Instance Activity"], dependencies=[require("api", instance_scope, Permission.audit_read)])
async def list_instance_activity(page: PageDep) -> PageEnvelope[ActivityOut]:
    """List the most recent audited changes across the instance."""
    return PageEnvelope.from_slice(await AuditLog.recent(page), ActivityOut)
