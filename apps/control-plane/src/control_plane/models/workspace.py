from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Self
from uuid import UUID

from pydantic import field_validator
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.common import Identified, OrgOwned, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.org_owned import NotOwnedError
from control_plane.models.common.slugs import SLUG_MAX_LENGTH, Slug, slugify
from control_plane.models.common.wire import RecordCreate, RecordOut, RecordUpdate
from control_plane.models.inference_key import InferenceKey
from control_plane.models.provider_credential import ProviderCredential
from control_plane.models.workspace_membership import WorkspaceMembership

if TYPE_CHECKING:
    from contract import SecretStore

DERIVED_SLUG_FALLBACK = "workspace"


def _as_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


@audited
class Workspace(Record, Identified, OrgOwned, Tombstonable, table=True):
    """The scope inference keys live in; membership is drawn from the owning org.

    The (id, org_id) unique constraint exists only as the composite foreign key target that
    keeps workspace-scoped rows structurally inside the workspace's org. The (org_id, slug) one
    is the domain rule: the slug is how a caller names a workspace within their org.
    """

    __table_args__: ClassVar = (
        UniqueConstraint("id", "org_id", name="workspace_id_org_id_key"),
        UniqueConstraint("org_id", "slug", name="workspace_org_id_slug_key"),
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

    async def delete_with_contents(self, store: SecretStore) -> None:
        """Delete the workspace with the rows scoped to it: its inference keys, its members, and the
        provider credentials it brought.

        A workspace's keys cannot outlive it, so revoked and live ones go together. The provider
        credentials take their values with them: the store is passed in because a model cannot reach
        the instance's, and a value left behind is a secret with no row to reach or remove it by.
        The usage it recorded is history rather than a scoped row, and stays.
        """
        await ProviderCredential.delete_scoped(store, ProviderCredential.workspace_id == self.id)
        for key in await InferenceKey.find(InferenceKey.workspace_id == self.id):
            await key.delete()
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
    name: str | None = Field(default=None, min_length=1, max_length=200)


class WorkspaceOut(RecordOut[Workspace]):
    id: UUID
    org_id: UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
