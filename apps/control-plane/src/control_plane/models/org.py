from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.common import Identified, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordCreate, RecordOut, RecordUpdate


@audited
class Org(Record, Identified, Tombstonable, table=True):
    name: str


class OrgCreate(RecordCreate[Org]):
    name: str = Field(description="Org name, e.g. My Org")


class OrgUpdate(RecordUpdate[Org]):
    name: str | None = None


class OrgOut(RecordOut[Org]):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
