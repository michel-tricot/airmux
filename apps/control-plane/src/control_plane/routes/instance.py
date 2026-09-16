from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from sqlmodel import col

from control_plane.authz import Permission
from control_plane.deps import instance_scope, require
from control_plane.models import AuditLog, DataPlaneInstance, RuntimeConfiguration
from control_plane.models.audit import ActivityOut
from control_plane.models.common.wire import Envelope
from control_plane.models.data_plane_instance import DataPlaneInstanceOut
from control_plane.models.runtime_configuration import InstancePublicationStatusOut  # noqa: TC001 FastAPI resolves route annotations at runtime

router = APIRouter(prefix="/instance")


@router.get("/bundles/status", tags=["Instance Model Catalog"], dependencies=[require("api", instance_scope, Permission.catalog_read)])
async def get_instance_bundle_publication_status() -> Envelope[InstancePublicationStatusOut]:
    """Summarize publication of the current global configuration revision."""
    return Envelope(data=await RuntimeConfiguration.instance_status())


@router.get("/data-planes", tags=["Data Plane Instances"], dependencies=[require("api", instance_scope, Permission.data_planes_read)])
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


@router.get("/activity", tags=["Instance Activity"], dependencies=[require("api", instance_scope, Permission.audit_read)])
async def list_instance_activity(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Envelope[list[ActivityOut]]:
    """List the most recent audited changes across the instance."""
    return Envelope(data=[ActivityOut.model_validate(entry) for entry in await AuditLog.recent(limit)])
