from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Self
from uuid import UUID

from sqlmodel import Field, col

from control_plane.models.audit import audited
from control_plane.models.common import Identified, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordCreate, RecordOut, RecordUpdate
from control_plane.models.org_membership import OrgMembership


@audited
class Org(Record, Identified, Tombstonable, table=True):
    name: str
    personal_for: UUID | None = Field(default=None, foreign_key="user.id", unique=True)

    api_readonly: ClassVar[frozenset[str]] = frozenset({"personal_for"})

    @classmethod
    async def personal_of(cls, user_id: UUID) -> Self | None:
        """The user's one self-founded org, whether or not they still hold a membership in it.

        The unique constraint on personal_for is the cap: racing claims collide on it at flush,
        so no guard code is needed anywhere.
        """
        return await cls.first(cls.personal_for == user_id)

    @classmethod
    async def joined_by(cls, user_id: UUID) -> list[Self]:
        """The orgs the user is a member of, by name."""
        memberships = await OrgMembership.find(OrgMembership.user_id == user_id)
        org_ids = [m.org_id for m in memberships]
        return await cls.find(col(cls.id).in_(org_ids), order_by=col(cls.name)) if org_ids else []


class OrgCreate(RecordCreate[Org]):
    name: str = Field(description="Org name, e.g. My Org")


class OrgUpdate(RecordUpdate[Org]):
    name: str | None = None


class OrgOut(RecordOut[Org]):
    id: UUID
    name: str
    personal_for: UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
