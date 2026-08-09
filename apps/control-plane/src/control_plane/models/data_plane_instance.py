from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlmodel import Field

from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut


class DataPlaneInstance(Record, table=True):
    """A data plane that has heartbeated, registered against the instance rather than any one org.

    A data plane polls whichever org's bundle its config names, so the registration itself carries
    no org: liveness is derived from last_seen and the row survives as history.
    """

    instance_id: UUID = Field(primary_key=True)
    version: str
    bundle_id: UUID | None = None
    address: str | None = None
    first_seen: datetime = Field(sa_type=UTCDateTime)
    last_seen: datetime = Field(sa_type=UTCDateTime)

    # A data plane is considered offline after three missed heartbeats; the row itself is never deleted.
    STALE_AFTER: ClassVar[timedelta] = timedelta(seconds=90)

    def status(self, now: datetime) -> Literal["online", "offline"]:
        last_seen = self.last_seen if self.last_seen.tzinfo else self.last_seen.replace(tzinfo=UTC)
        return "online" if now - last_seen < self.STALE_AFTER else "offline"


class DataPlaneInstanceOut(RecordOut[DataPlaneInstance]):
    instance_id: UUID
    version: str
    bundle_id: UUID | None
    address: str | None
    status: Literal["online", "offline"]
    first_seen: datetime
    last_seen: datetime

    api_extra: ClassVar[frozenset[str]] = frozenset({"status"})


class HeartbeatOut(BaseModel):
    instance_id: UUID
