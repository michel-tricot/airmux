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
    """org_id carries its own index: the primary key is user-first, so it cannot serve the
    by-org direction User.members_of and the workspace routes read, which would scan the table."""

    user_id: UUID = Field(primary_key=True, foreign_key="user.id")
    org_id: UUID = Field(primary_key=True, foreign_key="org.id", index=True)


class MembershipOut(BaseModel):
    user_id: UUID
    org_id: UUID
    status: Literal["member"]


class OrgMemberOut(BaseModel):
    """A member of the acting org: who they are and that they belong.

    Deliberately not UserOut: that carries the user's every membership, which would let one org's
    credential read the shape of the orgs it has no scope over.
    """

    user_id: UUID
    email: str
    name: str
    service_account: bool
    status: Literal["member"]
