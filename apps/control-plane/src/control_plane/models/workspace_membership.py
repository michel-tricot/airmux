from __future__ import annotations

from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import CheckConstraint, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Field

from control_plane.authz import WorkspaceRole
from control_plane.db import current_session
from control_plane.models.audit import audited
from control_plane.models.common import Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RequestModel
from control_plane.models.playground_session import PlaygroundSession


@audited
class WorkspaceMembership(Record, Tombstonable, table=True):
    """Membership in a workspace, structurally confined to the org.

    org_id is denormalized so two composite foreign keys carry the invariant that guard code
    would otherwise defend: the workspace must belong to the same org, and the user must hold
    an org membership. The cascade evicts the user from every workspace when their org
    membership is removed.
    """

    __table_args__: ClassVar = (
        CheckConstraint("role IN ('admin', 'member', 'viewer')", name="workspace_membership_role_valid"),
        ForeignKeyConstraint(["workspace_id", "org_id"], ["workspace.id", "workspace.org_id"]),
        ForeignKeyConstraint(["user_id", "org_id"], ["org_membership.user_id", "org_membership.org_id"], ondelete="CASCADE"),
    )

    user_id: UUID = Field(primary_key=True)
    workspace_id: UUID = Field(primary_key=True, index=True)
    org_id: UUID
    role: str = WorkspaceRole.member

    async def save(self) -> Self:
        await super().save()
        await PlaygroundSession.revoke_unsupported(self.user_id)
        return self

    async def delete(self) -> None:
        await super().delete()
        await PlaygroundSession.revoke_unsupported(self.user_id)

    @classmethod
    async def ensure(cls, *, user_id: UUID, workspace_id: UUID, org_id: UUID, role: str) -> None:
        statement = (
            insert(cls)
            .values(user_id=user_id, workspace_id=workspace_id, org_id=org_id, role=role)
            .on_conflict_do_nothing(index_elements=["user_id", "workspace_id"])
        )
        await current_session().execute(statement)


class WorkspaceMembershipIn(RequestModel):
    role: WorkspaceRole = Field(description="Workspace role to grant")


class WorkspaceMembershipOut(BaseModel):
    user_id: UUID
    workspace_id: UUID
    email: str
    name: str
    service_account: bool
    role: WorkspaceRole
    status: Literal["member"]


class WorkspaceMemberCandidateOut(BaseModel):
    user_id: UUID
    email: str
    name: str
    service_account: bool
