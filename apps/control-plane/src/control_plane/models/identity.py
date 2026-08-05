from __future__ import annotations

from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.base import Record
from control_plane.models.tombstone import Tombstonable


@audited
class User(Record, Tombstonable, table=True):
    id: str = Field(primary_key=True)
    email: str = Field(unique=True)
    name: str
    instance_admin: bool = False
    service_account: bool = False


@audited
class OrgMembership(Record, Tombstonable, table=True):
    user_id: str = Field(primary_key=True, foreign_key="user.id")
    org_id: str = Field(primary_key=True, foreign_key="org.id")


@audited
class MgmtToken(Record, Tombstonable, table=True):
    id: str = Field(primary_key=True)
    org_id: str | None = None
    user_id: str | None = Field(default=None, foreign_key="user.id")
    revoked: bool = False
