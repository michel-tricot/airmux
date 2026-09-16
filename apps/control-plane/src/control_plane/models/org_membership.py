from __future__ import annotations

from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import CheckConstraint, delete
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Field, col, select

from control_plane.authz import OrgRole
from control_plane.db import current_session
from control_plane.models.audit import audited
from control_plane.models.common import Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RequestModel


class LastOrgOwnerError(ValueError):
    def __init__(self) -> None:
        super().__init__("An organization must keep at least one owner")


@audited
class OrgMembership(Record, Tombstonable, table=True):
    """org_id carries its own index: the primary key is user-first, so it cannot serve the
    by-org direction User.members_of and the workspace routes read, which would scan the table."""

    __table_args__: ClassVar = (CheckConstraint("role IN ('owner', 'admin', 'member', 'data_plane')", name="org_membership_role_valid"),)

    user_id: UUID = Field(primary_key=True, foreign_key="user.id")
    org_id: UUID = Field(primary_key=True, foreign_key="org.id", index=True)
    role: str = OrgRole.member

    @classmethod
    async def ensure(cls, *, user_id: UUID, org_id: UUID, role: str) -> None:
        statement = insert(cls).values(user_id=user_id, org_id=org_id, role=role).on_conflict_do_nothing(index_elements=["user_id", "org_id"])
        await current_session().execute(statement)

    @classmethod
    async def delete_with_org(cls, org_id: UUID) -> None:
        await current_session().execute(delete(cls).where(col(cls.org_id) == org_id))

    async def _lock_org(self) -> None:
        from control_plane.models.org import Org  # noqa: PLC0415 org imports membership, so the two only meet at call time

        await current_session().execute(select(Org.id).where(Org.id == self.org_id).with_for_update())

    async def _refuse_last_owner_removal(self) -> None:
        await self._lock_org()
        owners = await OrgMembership.find(OrgMembership.org_id == self.org_id, OrgMembership.role == OrgRole.owner, limit=2)
        if len(owners) == 1 and owners[0].user_id == self.user_id:
            raise LastOrgOwnerError

    async def change_role(self, role: OrgRole) -> OrgMembership:
        if role != OrgRole.owner:
            await self._refuse_last_owner_removal()
        self.role = role
        return await self.save()

    async def delete(self) -> None:
        from control_plane.models.inference_key import InferenceKey  # noqa: PLC0415 membership and credential models meet at the operation
        from control_plane.models.playground_session import PlaygroundSession  # noqa: PLC0415 membership and credential models meet at the operation

        await self._refuse_last_owner_removal()
        await InferenceKey.revoke_owned_in_org(self.user_id, self.org_id)
        await PlaygroundSession.revoke_owned_in_org(self.user_id, self.org_id)
        await super().delete()


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
