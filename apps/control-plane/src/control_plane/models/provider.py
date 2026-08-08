from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.common import Identified, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordOut


@audited
class Provider(Record, Identified, Tombstonable, table=True):
    name: str = Field(unique=True)
    kind: str
    base_url: str
    credential_ref: str
    cache_read_multiplier: float = 1.0
    cache_write_multiplier: float = 1.0


class ProviderOut(RecordOut[Provider]):
    id: UUID
    name: str
    kind: str
    base_url: str
    credential_ref: str
    cache_read_multiplier: float
    cache_write_multiplier: float
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
