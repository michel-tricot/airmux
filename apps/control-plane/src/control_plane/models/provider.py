from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON
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
    icon: str = ""
    param_aliases: dict[str, str] = Field(default_factory=dict, sa_type=JSON)
    accepted_params: list[str] | None = Field(default=None, sa_type=JSON)
    params_closed: bool = False


class ProviderOut(RecordOut[Provider]):
    id: UUID
    name: str
    kind: str
    base_url: str
    icon: str
    param_aliases: dict[str, str]
    accepted_params: list[str] | None
    params_closed: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
