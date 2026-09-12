from __future__ import annotations

from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Field

from control_plane.authz import OrgRole
from control_plane.db import current_session
from control_plane.models.audit import audited
from control_plane.models.common import Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RequestModel
from control_plane.models.playground_session import PlaygroundSession


@audited
class OrgMembership(Record, Tombstonable, table=True):
    """org_id carries its own index: the primary key is user-first, so it cannot serve the
    by-org direction User.members_of and the workspace routes read, which would scan the table."""

    __table_args__: ClassVar = (CheckConstraint("role IN ('owner', 'admin', 'member', 'data_plane')", name="org_membership_role_valid"),)

    user_id: UUID = Field(primary_key=True, foreign_key="user.id")
    org_id: UUID = Field(primary_key=True, foreign_key="org.id", index=True)
    role: str = OrgRole.member

    async def save(self) -> Self:
        await super().save()
        await PlaygroundSession.revoke_unsupported(self.user_id)
        return self

    async def delete(self) -> None:
        await super().delete()
        await PlaygroundSession.revoke_unsupported(self.user_id)

    @classmethod
    async def ensure(cls, *, user_id: UUID, org_id: UUID, role: str) -> None:
        statement = insert(cls).values(user_id=user_id, org_id=org_id, role=role).on_conflict_do_nothing(index_elements=["user_id", "org_id"])
        await current_session().execute(statement)

    async def is_only_owner(self) -> bool:
        if self.role != OrgRole.owner:
            return False
        owners = await OrgMembership.find(OrgMembership.org_id == self.org_id, OrgMembership.role == OrgRole.owner)
        return len(owners) == 1


class OrgMembershipIn(RequestModel):
    role: OrgRole = Field(description="Organization role to grant")


class MembershipOut(BaseModel):
    user_id: UUID
    org_id: UUID
    role: OrgRole
    status: Literal["member"]


class OrgMemberOut(BaseModel):
    """A human user or service account that belongs to an organization."""

    user_id: UUID
    email: str
    name: str
    service_account: bool
    role: OrgRole
    status: Literal["member"]
    managed: bool = False
