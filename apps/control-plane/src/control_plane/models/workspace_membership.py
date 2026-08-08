from __future__ import annotations

from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import ForeignKeyConstraint
from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.common import Tombstonable
from control_plane.models.common.base import Record


@audited
class WorkspaceMembership(Record, Tombstonable, table=True):
    """Membership in a workspace, structurally confined to the org.

    org_id is denormalized so two composite foreign keys carry the invariant that guard code
    would otherwise defend: the workspace must belong to the same org, and the user must hold
    an org membership. The cascade evicts the user from every workspace when their org
    membership is removed.
    """

    __table_args__: ClassVar = (
        ForeignKeyConstraint(["workspace_id", "org_id"], ["workspace.id", "workspace.org_id"]),
        ForeignKeyConstraint(["user_id", "org_id"], ["org_membership.user_id", "org_membership.org_id"], ondelete="CASCADE"),
    )

    user_id: UUID = Field(primary_key=True)
    workspace_id: UUID = Field(primary_key=True)
    org_id: UUID


class WorkspaceMembershipOut(BaseModel):
    user_id: UUID
    workspace_id: UUID
    status: Literal["member"]
