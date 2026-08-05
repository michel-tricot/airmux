from __future__ import annotations

from sqlalchemy import JSON
from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.base import OrgOwned, Record
from control_plane.models.tombstone import Tombstonable


@audited
class Org(Record, Tombstonable, table=True):
    id: str = Field(primary_key=True)
    name: str


@audited
class ApiKey(Record, OrgOwned, Tombstonable, table=True):
    id: str = Field(primary_key=True)
    org_id: str = Field(foreign_key="org.id")
    allowed_models: list[str] = Field(default_factory=list, sa_type=JSON)
    disabled: bool = False
