from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlmodel import Field

from control_plane.models.base import Record
from control_plane.schemas import ApiOut


class DataPlaneInstance(Record, table=True):
    instance_id: str = Field(primary_key=True)
    org_id: str | None = None
    version: str
    bundle_id: UUID | None = None
    address: str | None = None
    first_seen: datetime
    last_seen: datetime

    # A data plane is considered offline after three missed heartbeats; the row itself is never deleted.
    STALE_AFTER: ClassVar[timedelta] = timedelta(seconds=90)

    def status(self, now: datetime) -> Literal["online", "offline"]:
        last_seen = self.last_seen if self.last_seen.tzinfo else self.last_seen.replace(tzinfo=UTC)
        return "online" if now - last_seen < self.STALE_AFTER else "offline"


class DataPlaneInstanceOut(ApiOut):
    instance_id: str
    org_id: str | None
    version: str
    bundle_id: UUID | None
    address: str | None
    status: Literal["online", "offline"]
    first_seen: datetime
    last_seen: datetime

    api_extra: ClassVar[frozenset[str]] = frozenset({"status"})


class HeartbeatOut(BaseModel):
    instance_id: str
