from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Self
from uuid import UUID

from pydantic import field_validator
from sqlalchemy import Index, UniqueConstraint, or_
from sqlalchemy.dialects.postgresql import CITEXT
from sqlmodel import Field, col, select

from control_plane.models.audit import audited
from control_plane.models.common import Identified, KeyColumn, OrgOwned, PageQuery, PageSlice, Tombstonable, UUID7Pageable
from control_plane.models.common.base import Record
from control_plane.models.common.org_owned import NotOwnedError
from control_plane.models.common.slugs import SLUG_MAX_LENGTH, Slug, slugify
from control_plane.models.common.wire import RecordCreate, RecordOut, RecordUpdate
from control_plane.models.inference_key import InferenceKey
from control_plane.models.management_key import ManagementKey
from control_plane.models.org_membership import OrgMembership
from control_plane.models.playground_session import PlaygroundSession
from control_plane.models.policy import Policy
from control_plane.models.provider_credential import ProviderCredential
from control_plane.models.user import User
from control_plane.models.workspace_membership import WorkspaceMembership

if TYPE_CHECKING:
    from airmux_runtime.secrets import SecretStore

DERIVED_SLUG_FALLBACK = "workspace"
type ReadableRoles = tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]


def _as_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


@audited
class Workspace(Record, Identified, OrgOwned, Tombstonable, UUID7Pageable, table=True):
    """The scope inference keys live in; membership is drawn from the owning org.

    The (id, org_id) unique constraint exists only as the composite foreign key target that
    keeps workspace-scoped rows structurally inside the workspace's org. The (org_id, slug) one
    is the domain rule: the slug is how a caller names a workspace within their org.
    """

    __table_args__: ClassVar = (
        UniqueConstraint("id", "org_id", name="workspace_id_org_id_key"),
        UniqueConstraint("org_id", "slug", name="workspace_org_id_slug_key"),
        Index("workspace_org_name_id_idx", "org_id", "name", "id"),
    )

    org_id: UUID = Field(foreign_key="org.id")
    name: str
    slug: str = Field(sa_type=CITEXT)

    api_immutable: ClassVar[frozenset[str]] = frozenset({"slug"})

    @classmethod
    async def by_ref(cls, org_id: UUID, ref: str) -> Self:
        """Resolve what a caller writes in a path: the workspace's id, or its slug within the org.

        The two namespaces cannot collide because WorkspaceCreate refuses a uuid-shaped slug.
        """
        ident = _as_uuid(ref)
        if ident is not None:
            return await cls.owned_by(org_id, ident)
        workspace = await cls.first(cls.org_id == org_id, cls.slug == ref)
        if workspace is None:
            raise NotOwnedError
        return workspace

    @classmethod
    async def slug_taken(cls, org_id: UUID, slug: str) -> bool:
        """Whether the org already holds this slug; the unique constraint is the real enforcement."""
        return await cls.first(cls.org_id == org_id, cls.slug == slug) is not None

    @classmethod
    async def free_slug(cls, org_id: UUID, name: str) -> str:
        """The slug for a workspace whose caller did not choose one: the name reduced to a slug,
        numbered past what the org already holds.

        The stem is trimmed before numbering so the suffix cannot push a derived slug past the
        length a caller would be allowed to write.
        """
        base = slugify(name) or DERIVED_SLUG_FALLBACK
        taken = {workspace.slug for workspace in await cls.find(cls.org_id == org_id)}
        if base not in taken:
            return base
        stem = base[: SLUG_MAX_LENGTH - 5].rstrip("-") or DERIVED_SLUG_FALLBACK
        suffix = 2
        while f"{stem}-{suffix}" in taken:
            suffix += 1
        return f"{stem}-{suffix}"

    @classmethod
    async def readable_by(
        cls,
        principal_id: UUID,
        org_id: UUID,
        *,
        instance_roles: tuple[str, ...],
        org_roles: tuple[str, ...],
        workspace_roles: tuple[str, ...],
    ) -> list[Self]:
        instance_access = select(User.id).where(col(User.id) == principal_id, col(User.instance_role).in_(instance_roles)).exists()
        org_access = (
            select(OrgMembership.user_id)
            .where(
                col(OrgMembership.user_id) == principal_id,
                col(OrgMembership.org_id) == org_id,
                col(OrgMembership.role).in_(org_roles),
            )
            .exists()
        )
        workspace_access = (
            select(WorkspaceMembership.user_id)
            .where(
                col(WorkspaceMembership.user_id) == principal_id,
                col(WorkspaceMembership.workspace_id) == col(cls.id),
                col(WorkspaceMembership.role).in_(workspace_roles),
            )
            .exists()
        )
        return await cls.find(cls.org_id == org_id, or_(instance_access, org_access, workspace_access), order_by=col(cls.name))

    @classmethod
    async def page_readable_by(
        cls,
        principal_id: UUID,
        org_id: UUID,
        request: PageQuery,
        *,
        roles: ReadableRoles,
    ) -> PageSlice[Self]:
        instance_roles, org_roles, workspace_roles = roles
        instance_access = select(User.id).where(col(User.id) == principal_id, col(User.instance_role).in_(instance_roles)).exists()
        org_access = (
            select(OrgMembership.user_id)
            .where(
                col(OrgMembership.user_id) == principal_id,
                col(OrgMembership.org_id) == org_id,
                col(OrgMembership.role).in_(org_roles),
            )
            .exists()
        )
        workspace_access = (
            select(WorkspaceMembership.user_id)
            .where(
                col(WorkspaceMembership.user_id) == principal_id,
                col(WorkspaceMembership.workspace_id) == col(cls.id),
                col(WorkspaceMembership.role).in_(workspace_roles),
            )
            .exists()
        )
        return await cls._page(
            select(cls).where(cls.org_id == org_id, or_(instance_access, org_access, workspace_access)),
            request,
            filter_columns=("org_id",),
            cursor_context={"org_id": org_id},
            columns=(KeyColumn(col(cls.name), "asc", "str"), KeyColumn(col(cls.id), "asc", "uuid")),
        )

    async def delete_with_contents(self, store: SecretStore) -> None:
        """Delete the workspace with the rows scoped to it: its inference keys, its members, and the
        provider credentials it brought.

        A workspace's keys cannot outlive it, so revoked and live ones go together. The provider
        credentials take their values with them: the store is passed in because a model cannot reach
        the instance's, and a value left behind is a secret with no row to reach or remove it by.
        The usage it recorded is history rather than a scoped row, and stays.
        """
        await ProviderCredential.delete_scoped(store, ProviderCredential.workspace_id == self.id)
        await ManagementKey.delete_scoped(ManagementKey.workspace_id == self.id)
        for policy in await Policy.for_workspace(self.id):
            await policy.delete()
        for key in await InferenceKey.find(InferenceKey.workspace_id == self.id):
            await key.delete()
        for playground_session in await PlaygroundSession.find(PlaygroundSession.workspace_id == self.id):
            await playground_session.delete()
        for membership in await WorkspaceMembership.find(WorkspaceMembership.workspace_id == self.id):
            await membership.delete()
        await self.delete()


class WorkspaceCreate(RecordCreate[Workspace]):
    name: str = Field(description="Workspace name, e.g. Staging", min_length=1, max_length=200)
    slug: Slug = Field("", description="Workspace handle, unique in the org and usable in place of the id; derived from the name when omitted")

    @field_validator("slug")
    @classmethod
    def reject_uuid_shaped(cls, slug: str) -> str:
        """A uuid-shaped slug would be unreachable in the paths that accept either, so it is not a slug."""
        if _as_uuid(slug) is not None:
            msg = "slug must not be a uuid"
            raise ValueError(msg)
        return slug


class WorkspaceUpdate(RecordUpdate[Workspace]):
    name: str | None = Field(default=None, description="Replacement workspace name", min_length=1, max_length=200)


class WorkspaceOut(RecordOut[Workspace]):
    id: UUID
    org_id: UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
