from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from control_plane.models.base import Record


class User(Record, table=True):
    id: str = Field(primary_key=True)
    email: str = Field(unique=True)
    name: str
    instance_admin: bool = False
    service_account: bool = False
    created_at: datetime


class OrgMembership(Record, table=True):
    user_id: str = Field(primary_key=True, foreign_key="user.id")
    org_id: str = Field(primary_key=True, foreign_key="org.id")


class MgmtToken(Record, table=True):
    id: str = Field(primary_key=True)
    org_id: str | None = None
    user_id: str | None = Field(default=None, foreign_key="user.id")
    created_at: datetime
    revoked: bool = False
