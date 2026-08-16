from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import ForeignKeyConstraint
from sqlmodel import Field

from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut


class DataPlaneInstance(Record, table=True):
    """A data plane that has heartbeated at either the global or organization boundary.

    Instance-bound keys register global data planes. Organization-bound keys register dedicated
    data planes, and the org link is cleared on deletion while the row survives as history.
    """

    __table_args__: ClassVar = (ForeignKeyConstraint(["org_id"], ["org.id"], ondelete="SET NULL"),)

    instance_id: UUID = Field(primary_key=True)
    org_id: UUID | None = None
    version: str
    bundle_id: UUID | None = None
    address: str | None = None
    first_seen: datetime = Field(sa_type=UTCDateTime)
    last_seen: datetime = Field(sa_type=UTCDateTime)

    STALE_AFTER: ClassVar[timedelta] = timedelta(seconds=90)

    def status(self, now: datetime) -> Literal["online", "offline"]:
        last_seen = self.last_seen if self.last_seen.tzinfo else self.last_seen.replace(tzinfo=UTC)
        return "online" if now - last_seen < self.STALE_AFTER else "offline"


class DataPlaneInstanceOut(RecordOut[DataPlaneInstance]):
    instance_id: UUID
    org_id: UUID | None
    version: str
    bundle_id: UUID | None
    address: str | None
    status: Literal["online", "offline"]
    first_seen: datetime
    last_seen: datetime

    api_extra: ClassVar[frozenset[str]] = frozenset({"status"})


class HeartbeatOut(BaseModel):
    instance_id: UUID
