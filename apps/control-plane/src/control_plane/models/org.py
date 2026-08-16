from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Self
from uuid import UUID

from sqlmodel import Field, col, select

from control_plane.models.access_key import AccessKey
from control_plane.models.audit import audited
from control_plane.models.bundle import Bundle
from control_plane.models.common import Identified, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordCreate, RecordOut, RecordUpdate
from control_plane.models.org_membership import OrgMembership
from control_plane.models.provider_credential import ProviderCredential
from control_plane.models.workspace import Workspace

if TYPE_CHECKING:
    from contract import SecretStore


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
        """The orgs the user is a member of, by name; the mirror of User.members_of, one query like it."""
        return await cls.find(
            col(cls.id).in_(select(OrgMembership.org_id).where(OrgMembership.user_id == user_id)),
            order_by=col(cls.name),
        )

    async def delete_with_contents(self, store: SecretStore) -> None:
        """Delete the org and everything scoped to it: workspaces with their keys, members and
        provider credentials, then its own credentials, access keys, memberships, bundles.

        Everything removed here exists only to serve the org. What is history rather than structure
        stays: usage events keep the ids they were written with, and the audit trail keeps its rows,
        neither holding a foreign key into what it records.
        """
        for workspace in await Workspace.find(Workspace.org_id == self.id):
            await workspace.delete_with_contents(store)
        await ProviderCredential.delete_scoped(store, ProviderCredential.org_id == self.id)
        await AccessKey.delete_scoped(AccessKey.org_id == self.id)
        for membership in await OrgMembership.find(OrgMembership.org_id == self.id):
            await membership.delete()
        for bundle in await Bundle.find(Bundle.org_id == self.id):
            await bundle.delete()
        await self.delete()


class OrgCreate(RecordCreate[Org]):
    name: str = Field(description="Org name, e.g. My Org", min_length=1, max_length=200)


class OrgUpdate(RecordUpdate[Org]):
    name: str | None = Field(default=None, min_length=1, max_length=200)


class OrgOut(RecordOut[Org]):
    id: UUID
    name: str
    personal_for: UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
