from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON
from sqlmodel import Field

from control_plane.models.base import OrgOwned, Record


class Org(Record, table=True):
    id: str = Field(primary_key=True)
    name: str
    created_at: datetime


class ApiKey(OrgOwned, table=True):
    id: str = Field(primary_key=True)
    org_id: str = Field(foreign_key="org.id")
    allowed_models: list[str] = Field(default_factory=list, sa_type=JSON)
    disabled: bool = False
    created_at: datetime
