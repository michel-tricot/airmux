from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.base import Record
from control_plane.models.mixins import Tombstonable


@audited
class OrgMembership(Record, Tombstonable, table=True):
    user_id: str = Field(primary_key=True, foreign_key="user.id")
    org_id: str = Field(primary_key=True, foreign_key="org.id")


class MembershipOut(BaseModel):
    user_id: str
    org_id: str
    status: Literal["member"]
