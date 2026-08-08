from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.common import Tombstonable
from control_plane.models.common.base import Record


@audited
class OrgMembership(Record, Tombstonable, table=True):
    user_id: UUID = Field(primary_key=True, foreign_key="user.id")
    org_id: UUID = Field(primary_key=True, foreign_key="org.id")


class MembershipOut(BaseModel):
    user_id: UUID
    org_id: UUID
    status: Literal["member"]
