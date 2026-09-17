from __future__ import annotations

import contextlib
from datetime import datetime
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import Field as PydanticField
from pydantic import SecretStr, field_validator
from sqlalchemy import CheckConstraint, ColumnElement, ForeignKeyConstraint, Index, String, UniqueConstraint, or_
from sqlalchemy.dialects.postgresql import CITEXT
from sqlmodel import Field, col

from airmux_runtime.secrets import SecretNotFoundError, SecretRejectedError, SecretStore
from contract import CredentialScope, SecretPurpose, SecretRef
from control_plane.db import current_session
from control_plane.models.audit import audited
from control_plane.models.common import Identified, PageQuery, PageSlice, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.org_owned import NotOwnedError
from control_plane.models.common.wire import RecordOut, RecordUpdate, RequestModel
from control_plane.models.runtime_configuration import bundle_input

DEFAULT_PRIORITY = 100
ProviderCredentialStatus = Literal["unknown", "live", "invalid", "rate_limited"]


@audited
@bundle_input(
    scope="nullable_org",
    columns=("org_id", "workspace_id", "provider_name", "name", "priority", "enabled", "version"),
)
class ProviderCredential(Record, Identified, Tombstonable, table=True):
    """One provider API key the platform holds on someone's behalf. The value is not here.

    Deliberately not OrgOwned: a platform credential belongs to the instance rather than to a
    tenant, so org_id is nullable and owned_by cannot apply. Org-scoped reads go through in_org()
    and for_org(), which carry the same NotOwnedError contract.

    Scope is derived from which owner fields are set rather than stored, so a row cannot claim one
    scope while carrying another's ownership. The check constraint covers the one combination the
    composite foreign key does not: a MATCH SIMPLE key with a null column is not checked at all, so
    a workspace credential with no org would otherwise pass.

    There is no value column and there is no location column. The value lives in the secret store,
    addressed by secret_ref, which the row builds from its own fields alone. That is deliberate
    twice over: the audit trigger copies before and after of every column, so a value column would
    write secrets into a second table, and a location column would be something a tenant, an
    operator, or a migration could point somewhere it should not go.

    provider_name is the one field that looks redundant beside provider_id and is not. The value was
    written under that name, so it is where the secret actually is rather than a copy of the
    catalog: a provider renamed later must not move every credential's secret out from under it.
    Keeping it here is also what lets secret_ref take no arguments, so no caller can pass the name
    of a provider this credential does not belong to and address somebody else's secret.
    """

    __table_args__: ClassVar = (
        ForeignKeyConstraint(["workspace_id", "org_id"], ["workspace.id", "workspace.org_id"]),
        UniqueConstraint(
            "org_id",
            "workspace_id",
            "provider_id",
            "name",
            name="provider_credential_scope_name_key",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("workspace_id IS NULL OR org_id IS NOT NULL", name="provider_credential_workspace_needs_org"),
        Index("provider_credential_org_order_idx", "org_id", "priority", "name", "id"),
        Index("provider_credential_workspace_order_idx", "org_id", "workspace_id", "priority", "name", "id"),
        Index("provider_credential_org_id_idx", "org_id", "id"),
        Index("provider_credential_workspace_id_idx", "org_id", "workspace_id", "id"),
    )

    org_id: UUID | None = Field(default=None, foreign_key="org.id")
    workspace_id: UUID | None = None
    provider_id: UUID = Field(foreign_key="provider.id")
    provider_name: str
    name: str = Field(sa_type=CITEXT)
    priority: int = DEFAULT_PRIORITY
    enabled: bool = True
    version: int = 1
    status: ProviderCredentialStatus = Field(default="unknown", sa_type=String)
    status_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    fingerprint: str = ""

    api_readonly: ClassVar[frozenset[str]] = frozenset(
        {"org_id", "workspace_id", "provider_id", "provider_name", "name", "version", "status", "status_at", "fingerprint"}
    )

    @property
    def scope(self) -> CredentialScope:
        if self.org_id is None:
            return "platform"
        return "workspace" if self.workspace_id is not None else "org"

    def secret_ref(self) -> SecretRef:
        """Where the value is, said in domain terms and derived from this row alone.

        The one place a row becomes a ref, so the write path, the compiler and the delete path
        cannot disagree about which secret a row names.
        """
        return SecretRef(
            purpose=SecretPurpose.provider,
            service=self.provider_name,
            name=self.name,
            secret_id=self.id,
            org_id=self.org_id,
            workspace_id=self.workspace_id,
        )

    @classmethod
    async def in_org(cls, org_id: UUID, ident: UUID) -> Self:
        """One credential the org owns. The owned_by contract for a table that is not OrgOwned:
        a platform credential is never reachable through an org, so it raises rather than leaking."""
        credential = await cls.find_by_id(ident)
        if credential is None or credential.org_id != org_id:
            raise NotOwnedError
        return credential

    @classmethod
    async def for_org(cls, org_id: UUID, workspace_id: UUID | None = None) -> list[Self]:
        """An org's credentials, or one workspace's within it, in the order the data plane tries them."""
        scoped = (cls.workspace_id == workspace_id,) if workspace_id is not None else ()
        return await cls.find(cls.org_id == org_id, *scoped, order_by=(cls.priority, cls.name))  # ty: ignore[invalid-argument-type] sqlmodel columns type as their python values

    @classmethod
    async def for_instance(cls) -> list[Self]:
        """Instance credentials in the order the data plane tries them."""
        return await cls.find(col(cls.org_id).is_(None), order_by=(cls.priority, cls.name))  # ty: ignore[invalid-argument-type] sqlmodel columns type as their python values

    @classmethod
    async def page_for_scope(cls, org_id: UUID | None, workspace_id: UUID | None, request: PageQuery) -> PageSlice[Self]:
        partition = {"org_id": org_id, "workspace_id": workspace_id} if workspace_id is not None else {"org_id": org_id}
        return await cls.page(request, partition=partition)

    async def delete_with_value(self, store: SecretStore) -> None:
        """Delete the credential and the value behind it.

        The value goes first, for the same reason the create path writes the row first: a row whose
        value is gone is a candidate the request path skips, while a value whose row is gone is a
        secret nothing knows how to reach or remove. A store that never held the value has nothing
        to remove, so its refusal is not a failure here.
        """
        with contextlib.suppress(SecretRejectedError, SecretNotFoundError):
            await store.delete(self.secret_ref())
        await self.delete()

    @classmethod
    async def delete_scoped(cls, store: SecretStore, *conditions: ColumnElement[bool] | bool) -> None:
        """Delete every credential matching the conditions, values included.

        This is what a workspace or an org delete calls. It exists because a credential holds a
        foreign key into both, so leaving one behind does not orphan a row, it makes the workspace
        or the org undeletable.
        """
        for credential in await cls.find(*conditions):
            await credential.delete_with_value(store)

    @classmethod
    async def observe(cls, observations: dict[UUID, tuple[datetime, ProviderCredentialStatus]], org_id: UUID | None = None) -> None:
        """Record what the data plane saw of each credential, from the usage events just ingested.

        Advisory and best effort: the status tells an operator which key to look at, and nothing on
        the request path reads it. A credential the events name but the table does not, or that
        belongs to another organization, is skipped. Deleted credentials can still have events in
        flight, and an organization-bound data plane cannot change another tenant's health.

        status_at is what makes this safe under at-least-once delivery: events replay after an
        outage and arrive out of order, so an older observation must never overwrite a newer one and
        flip a working key back to invalid.

        One select and one flush however many credentials a batch names: the outbox drains up to a
        thousand events at a time, so a query per credential would put the ingest path's cost on the
        number of keys an org happens to hold.
        """
        if not observations:
            return
        tenant = () if org_id is None else (or_(col(cls.org_id) == org_id, col(cls.org_id).is_(None)),)
        credentials = await cls.find(col(cls.id).in_(observations), *tenant)
        touched = False
        for credential in credentials:
            observed_at, status = observations[credential.id]
            if credential.status_at is not None and credential.status_at >= observed_at:
                continue
            credential.status = status
            credential.status_at = observed_at
            touched = True
        if touched:
            await current_session().flush()

    @classmethod
    async def named(cls, org_id: UUID | None, workspace_id: UUID | None, provider_id: UUID, name: str) -> Self | None:
        """The row the uniqueness constraint describes, which is what a rotation addresses."""
        return await cls.first(cls.org_id == org_id, cls.workspace_id == workspace_id, cls.provider_id == provider_id, cls.name == name)


class ProviderCredentialIn(RequestModel):
    """A provider API key and the metadata used to select it."""

    provider: str = PydanticField(
        description="Provider name from the catalog, e.g. openai",
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    name: str = PydanticField(
        default="default",
        description="Handle for this key within the provider and scope, e.g. prod or backup",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )
    value: SecretStr = PydanticField(description="The provider API key; stored securely and never returned", min_length=1, max_length=16384)
    priority: int = PydanticField(default=DEFAULT_PRIORITY, ge=0, le=1_000_000, description="Lower is tried first; ties break by name")

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, provider: object) -> object:
        return provider.strip().casefold() if isinstance(provider, str) else provider


class ProviderCredentialValueIn(RequestModel):
    """A rotation: the same credential, a new value."""

    value: SecretStr = PydanticField(description="The replacement provider API key", min_length=1, max_length=16384)


class ProviderCredentialUpdate(RecordUpdate[ProviderCredential]):
    priority: int | None = PydanticField(default=None, description="Replacement selection priority; lower values are tried first", ge=0, le=1_000_000)
    enabled: bool | None = PydanticField(default=None, description="Whether the credential may be selected for requests")


class ProviderCredentialOut(RecordOut[ProviderCredential]):
    id: UUID
    org_id: UUID | None
    workspace_id: UUID | None
    provider_id: UUID
    provider_name: str
    name: str
    priority: int
    enabled: bool
    version: int
    status: ProviderCredentialStatus
    status_at: datetime | None
    fingerprint: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    scope: CredentialScope

    api_extra: ClassVar[frozenset[str]] = frozenset({"scope"})
