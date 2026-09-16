from __future__ import annotations

from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import CheckConstraint, delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Field, col, select

from control_plane.authz import OrgRole
from control_plane.db import current_session
from control_plane.models.audit import audited
from control_plane.models.common import KeyColumn, Keyset, PageQuery, PageSlice, Tombstonable, keyset_page
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

    @classmethod
    async def page_for_user(cls, user_id: UUID, request: PageQuery) -> PageSlice[Self]:
        return await keyset_page(
            select(cls).where(cls.user_id == user_id),
            request,
            Keyset(model=cls, filter_columns=("user_id",), columns=(KeyColumn(col(cls.org_id), "asc", "uuid"),)),
            cursor_context={"user_id": user_id},
        )

    @classmethod
    async def roles_for_org_users(cls, org_id: UUID, user_ids: tuple[UUID, ...]) -> dict[UUID, OrgRole]:
        if not user_ids:
            return {}
        memberships = await cls.find(cls.org_id == org_id, col(cls.user_id).in_(user_ids))
        return {membership.user_id: OrgRole(membership.role) for membership in memberships}

    @classmethod
    async def count_for_user(cls, user_id: UUID, visible_org_id: UUID | None = None) -> int:
        statement = select(func.count()).select_from(cls).where(cls.user_id == user_id)
        if visible_org_id is not None:
            statement = statement.where(cls.org_id == visible_org_id)
        return (await current_session().execute(statement)).scalar_one()

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
