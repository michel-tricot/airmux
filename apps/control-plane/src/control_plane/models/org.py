from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Self
from uuid import UUID

from pydantic import field_validator
from sqlalchemy import Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlmodel import Field, col, select

from control_plane.db import current_session
from control_plane.models.audit import audited
from control_plane.models.bundle import Bundle
from control_plane.models.common import Identified, KeyColumn, PageQuery, PageSlice, Tombstonable, UUID7Pageable
from control_plane.models.common.base import Record
from control_plane.models.common.slugs import SLUG_MAX_LENGTH, Slug, slugify
from control_plane.models.common.wire import RecordCreate, RecordOut, RecordUpdate
from control_plane.models.management_key import ManagementKey
from control_plane.models.org_membership import OrgMembership
from control_plane.models.provider_credential import ProviderCredential
from control_plane.models.workspace import Workspace

if TYPE_CHECKING:
    from contract import SecretStore

DERIVED_SLUG_FALLBACK = "organization"


class OrgSlugTakenError(Exception):
    pass


def _as_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


@audited
class Org(Record, Identified, Tombstonable, UUID7Pageable, table=True):
    __table_args__: ClassVar = (UniqueConstraint("slug", name="org_slug_key"), Index("org_name_id_idx", "name", "id"))

    name: str
    slug: str = Field(sa_type=CITEXT)
    personal_for: UUID | None = Field(default=None, foreign_key="user.id", unique=True)

    api_readonly: ClassVar[frozenset[str]] = frozenset({"personal_for"})
    api_immutable: ClassVar[frozenset[str]] = frozenset({"slug"})

    @classmethod
    async def by_ref(cls, ref: str) -> Self | None:
        ident = _as_uuid(ref)
        return await cls.find_by_id(ident) if ident is not None else await cls.first(cls.slug == ref)

    @classmethod
    async def slug_taken(cls, slug: str) -> bool:
        return await cls.first(cls.slug == slug) is not None

    @classmethod
    async def free_slug(cls, name: str) -> str:
        base = slugify(name) or DERIVED_SLUG_FALLBACK
        taken = {org.slug for org in await cls.find()}
        if base not in taken:
            return base
        stem = base[: SLUG_MAX_LENGTH - 5].rstrip("-") or DERIVED_SLUG_FALLBACK
        suffix = 2
        while f"{stem}-{suffix}" in taken:
            suffix += 1
        return f"{stem}-{suffix}"

    @classmethod
    async def create(cls, name: str, slug: str = "", personal_for: UUID | None = None) -> Self:
        if slug and await cls.slug_taken(slug):
            raise OrgSlugTakenError
        return await cls(name=name, slug=slug or await cls.free_slug(name), personal_for=personal_for).save()

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

    @classmethod
    async def page_all(cls, request: PageQuery) -> PageSlice[Self]:
        return await cls._page(
            select(cls),
            request,
            columns=(KeyColumn(col(cls.name), "asc", "str"), KeyColumn(col(cls.id), "asc", "uuid")),
        )

    @classmethod
    async def page_joined_by(cls, user_id: UUID, visible_org_id: UUID | None, request: PageQuery) -> PageSlice[Self]:
        statement = select(cls).where(col(cls.id).in_(select(OrgMembership.org_id).where(OrgMembership.user_id == user_id)))
        if visible_org_id is not None:
            statement = statement.where(cls.id == visible_org_id)
        return await cls._page(
            statement,
            request,
            cursor_context={"user_id": user_id, "visible_org_id": visible_org_id},
            columns=(KeyColumn(col(cls.name), "asc", "str"), KeyColumn(col(cls.id), "asc", "uuid")),
        )

    @classmethod
    async def count_joined_by(cls, user_id: UUID, visible_org_id: UUID | None) -> int:
        statement = select(func.count()).select_from(cls).where(col(cls.id).in_(select(OrgMembership.org_id).where(OrgMembership.user_id == user_id)))
        if visible_org_id is not None:
            statement = statement.where(cls.id == visible_org_id)
        return (await current_session().execute(statement)).scalar_one()

    async def delete_with_contents(self, store: SecretStore) -> None:
        """Delete the org and everything scoped to it: workspaces with their keys, members and
        provider credentials, then its own credentials, management keys, memberships, bundles.

        Everything removed here exists only to serve the org. What is history rather than structure
        stays: usage events keep the ids they were written with, and the audit trail keeps its rows,
        neither holding a foreign key into what it records.
        """
        for workspace in await Workspace.find(Workspace.org_id == self.id):
            await workspace.delete_with_contents(store)
        await ProviderCredential.delete_scoped(store, ProviderCredential.org_id == self.id)
        await ManagementKey.delete_scoped(ManagementKey.org_id == self.id)
        await OrgMembership.delete_with_org(self.id)
        for bundle in await Bundle.find(Bundle.org_id == self.id):
            await bundle.delete()
        from control_plane.models.user import User  # noqa: PLC0415 user imports org membership, so org-owned accounts meet it at deletion

        for service_account in await User.find(User.managing_org_id == self.id):
            await service_account.delete_with_contents()
        await self.delete()


class OrgCreate(RecordCreate[Org]):
    name: str = Field(description="Org name, e.g. My Org", min_length=1, max_length=200)
    slug: Slug = Field("", description="Organization handle, globally unique and usable in place of the id; derived from the name when omitted")

    @field_validator("slug")
    @classmethod
    def reject_uuid_shaped(cls, slug: str) -> str:
        if _as_uuid(slug) is not None:
            msg = "slug must not be a uuid"
            raise ValueError(msg)
        return slug


class OrgUpdate(RecordUpdate[Org]):
    name: str | None = Field(default=None, description="Replacement organization name", min_length=1, max_length=200)


class OrgOut(RecordOut[Org]):
    id: UUID
    name: str
    slug: str
    personal_for: UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
