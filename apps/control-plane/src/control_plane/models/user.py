from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlmodel import Field, col, select

from control_plane.db import current_session
from control_plane.models.audit import audited
from control_plane.models.common import Identified, Tombstonable, slugify
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordCreate, RecordOut
from control_plane.models.org_membership import OrgMembership

SERVICE_ACCOUNT_EMAIL_DOMAIN = "airbytesvcaccount.ai"

# Advisory lock key for the instance claim. Arbitrary and constant: it names the claim, nothing else.
_CLAIM_LOCK = 0x41524C4C


@audited
class User(Record, Identified, Tombstonable, table=True):
    email: str = Field(unique=True)
    name: str
    instance_admin: bool = False
    service_account: bool = False

    api_hidden: ClassVar[frozenset[str]] = frozenset({"instance_admin"})
    api_readonly: ClassVar[frozenset[str]] = frozenset({"service_account"})
    api_immutable: ClassVar[frozenset[str]] = frozenset({"email"})

    @classmethod
    async def members_of(cls, org_id: UUID) -> list[Self]:
        """The users holding a membership in the org, by email; the mirror of Org.joined_by.

        The membership ids stay in the database as a subquery rather than round-tripping through
        Python: Postgres plans it as the same hash join an explicit join would produce, and an
        empty org is an empty result instead of a case to guard.
        """
        return await cls.find(
            col(cls.id).in_(select(OrgMembership.user_id).where(OrgMembership.org_id == org_id)),
            order_by=col(cls.email),
        )

    @classmethod
    async def instance_claimed(cls) -> bool:
        """Whether any human account exists. Service accounts do not claim an instance."""
        return await cls.first(col(cls.service_account).is_(False)) is not None

    @classmethod
    async def claims_the_instance(cls) -> bool:
        """Whether the account about to be created is the first human, and so founds the deployment.

        The transaction-scoped advisory lock serializes the check against the insert that follows
        it, so two signups racing on a fresh deployment cannot both come back true; the loser sees
        the winner's row. The lock dies with the transaction, and it is taken only while the
        instance is unclaimed, so it costs a signup nothing once someone holds an account.
        """
        await current_session().execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CLAIM_LOCK})
        return not await cls.instance_claimed()

    async def backs_org(self, org_id: UUID) -> bool:
        """Whether this user's authority covers the org: instance admins everywhere, everyone else by membership.

        The rule every org-scoped credential is checked against, so it has one home rather than one per door.
        """
        return self.instance_admin or await OrgMembership.get((self.id, org_id)) is not None

    async def delete_with_contents(self) -> None:
        """Delete the user with the entities they own that are theirs alone: identities, sessions, management and instance keys.

        The sibling of Org.delete_with_contents and Workspace.delete_with_contents. Everything else a
        user touches outlives them, so the route refuses rather than cascading: a membership is the
        org's decision, a personal org is a tenant, an inference key belongs to its workspace.
        """
        from control_plane import models  # noqa: PLC0415 auth_identity imports user, so the two only meet at call time

        for owned in (models.AuthIdentity, models.AuthSession, models.ManagementKey, models.InstanceKey):
            for record in await owned.find(owned.user_id == self.id):
                await record.delete()
        await self.delete()

    @classmethod
    def new_service_account(cls, name: str) -> Self:
        """Machine principal with a derived unique email; the caller saves it and adds memberships."""
        return cls(
            email=f"{slugify(name)}-{uuid4().hex[:8]}@{SERVICE_ACCOUNT_EMAIL_DOMAIN}",
            name=name,
            service_account=True,
        )


class UserCreate(RecordCreate[User]):
    email: str = Field(description="Unique email identifying the user")
    name: str = Field("", description="Display name, defaults to the email")


class ServiceAccountIn(BaseModel):
    name: str = Field(description="Service account name; the email is derived as name-<id>@airbytesvcaccount.ai")

    @field_validator("name")
    @classmethod
    def name_yields_an_email_local_part(cls, v: str) -> str:
        if not slugify(v):
            msg = "name must contain at least one letter or digit"
            raise ValueError(msg)
        return v


class UserOut(RecordOut[User]):
    id: UUID
    email: str
    name: str
    service_account: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    orgs: list[UUID]

    api_extra: ClassVar[frozenset[str]] = frozenset({"orgs"})
