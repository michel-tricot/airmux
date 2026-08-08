from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from sqlmodel import Field

from control_plane.models.common import OrgOwned
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut


class Bundle(Record, OrgOwned, table=True):
    id: UUID = Field(primary_key=True)
    org_id: UUID = Field(foreign_key="org.id")
    version: int
    issued_at: datetime = Field(sa_type=UTCDateTime)
    expires_at: datetime = Field(sa_type=UTCDateTime)
    payload: str
    signature: str
    signing_key_id: str

    api_hidden: ClassVar[frozenset[str]] = frozenset({"payload", "signature"})


class BundleOut(RecordOut[Bundle]):
    id: UUID
    org_id: UUID
    version: int
    issued_at: datetime
    expires_at: datetime
    signing_key_id: str
