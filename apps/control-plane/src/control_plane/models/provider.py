from __future__ import annotations

from datetime import datetime  # noqa: TC003 pydantic resolves field annotations at runtime

from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.base import Record
from control_plane.models.mixins import Tombstonable
from control_plane.schemas import ApiOut


@audited
class Provider(Record, Tombstonable, table=True):
    id: str = Field(primary_key=True)
    kind: str
    base_url: str
    credential_ref: str
    cache_read_multiplier: float = 1.0
    cache_write_multiplier: float = 1.0


class ProviderOut(ApiOut):
    id: str
    kind: str
    base_url: str
    credential_ref: str
    cache_read_multiplier: float
    cache_write_multiplier: float
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
