from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, field_validator
from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, func, or_, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlmodel import Field, col, select

from control_plane.authz import InstanceRole, OrgRole
from control_plane.db import current_session
from control_plane.models.audit import audited
from control_plane.models.common import Identified, NotOwnedError, PageQuery, PageSlice, Tombstonable, slugify
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordOut, RequestModel
from control_plane.models.management_key import ManagementKeyCreatedOut, ManagementKeyIn
from control_plane.models.org_membership import MembershipOut, OrgMembership
from control_plane.models.workspace_membership import WorkspaceMembership

SERVICE_ACCOUNT_EMAIL_DOMAIN = "service-account.airmux.invalid"
EMAIL_MAX_LENGTH = 320

_INSTANCE_OWNER_LOCK = 0x41524C4C


class LastInstanceOwnerError(ValueError):
    def __init__(self) -> None:
        super().__init__("An instance must keep at least one owner")


class ManagedServiceAccountInstanceRoleError(ValueError):
    def __init__(self) -> None:
        super().__init__("Organization-managed service accounts cannot hold an instance role")


@audited
class User(Record, Identified, Tombstonable, table=True):
    __table_args__: ClassVar = (
        CheckConstraint("instance_role IS NULL OR instance_role IN ('owner', 'auditor', 'data_plane')", name="user_instance_role_valid"),
        CheckConstraint(
            "managing_org_id IS NULL OR (service_account AND instance_role IS NULL)",
            name="user_managing_org_requires_org_scoped_service_account",
        ),
        Index("user_service_account_id_idx", "service_account", "id"),
    )

    email: str = Field(unique=True, sa_type=CITEXT)
    name: str
    instance_role: str | None = None
    service_account: bool = False
    managing_org_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("org.id", name="user_managing_org_id_fkey", use_alter=True), index=True),
    )

    api_readonly: ClassVar[frozenset[str]] = frozenset({"service_account", "managing_org_id"})
    api_immutable: ClassVar[frozenset[str]] = frozenset({"email"})

    @staticmethod
    def normalize_email(email: str) -> str:
        normalized = email.strip().casefold()
        local, separator, domain = normalized.partition("@")
        if not separator or not local or not domain or len(normalized) > EMAIL_MAX_LENGTH:
            msg = "email must be a valid address"
            raise ValueError(msg)
        return normalized

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
    async def org_member_for_email(cls, org_id: UUID, email: str) -> OrgMembership | None:
        query = (
            select(OrgMembership)
            .join(cls, col(cls.id) == col(OrgMembership.user_id))
            .where(OrgMembership.org_id == org_id, cls.email == cls.normalize_email(email))
        )
        return (await current_session().execute(query)).scalar_one_or_none()

    @classmethod
    async def workspace_members(cls, workspace_id: UUID) -> list[tuple[WorkspaceMembership, Self]]:
        query = (
            select(WorkspaceMembership, cls)
            .join(cls, col(cls.id) == col(WorkspaceMembership.user_id))
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .order_by(col(cls.email))
        )
        return [(membership, user) for membership, user in (await current_session().execute(query)).all()]

    @classmethod
    async def policy_candidates(cls, org_id: UUID, workspace_id: UUID) -> list[Self]:
        return await cls.find(
            col(cls.id).in_(
                select(OrgMembership.user_id).where(
                    OrgMembership.org_id == org_id,
                    or_(
                        col(OrgMembership.role).in_((OrgRole.owner, OrgRole.admin)),
                        select(WorkspaceMembership.user_id)
                        .where(
                            WorkspaceMembership.user_id == OrgMembership.user_id,
                            WorkspaceMembership.org_id == org_id,
                            WorkspaceMembership.workspace_id == workspace_id,
                        )
                        .exists(),
                    ),
                )
            ),
            order_by=col(cls.email),
        )

    @classmethod
    async def candidates_for_workspace(cls, org_id: UUID, workspace_id: UUID) -> list[Self]:
        return await cls.find(
            col(cls.id).in_(select(OrgMembership.user_id).where(OrgMembership.org_id == org_id)),
            ~select(WorkspaceMembership.user_id)
            .where(WorkspaceMembership.user_id == cls.id, WorkspaceMembership.workspace_id == workspace_id)
            .exists(),
            order_by=col(cls.email),
        )

    @classmethod
    async def page_for_instance(cls, request: PageQuery, service_account: bool | None) -> PageSlice[Self]:
        partition = {"service_account": service_account} if service_account is not None else None
        return await cls.page(request, partition=partition)

    @classmethod
    async def page_members_of(cls, org_id: UUID, request: PageQuery) -> PageSlice[Self]:
        condition = col(cls.id).in_(select(OrgMembership.user_id).where(OrgMembership.org_id == org_id))
        return await cls.page(request, condition)

    @classmethod
    async def page_workspace_members(cls, workspace_id: UUID, request: PageQuery) -> PageSlice[Self]:
        condition = (
            select(WorkspaceMembership.user_id)
            .where(WorkspaceMembership.user_id == cls.id, WorkspaceMembership.workspace_id == workspace_id)
            .exists()
        )
        return await cls.page(request, condition)

    @classmethod
    async def page_policy_candidates(cls, org_id: UUID, workspace_id: UUID, request: PageQuery) -> PageSlice[Self]:
        condition = col(cls.id).in_(
            select(OrgMembership.user_id).where(
                OrgMembership.org_id == org_id,
                or_(
                    col(OrgMembership.role).in_((OrgRole.owner, OrgRole.admin)),
                    select(WorkspaceMembership.user_id)
                    .where(
                        WorkspaceMembership.user_id == OrgMembership.user_id,
                        WorkspaceMembership.org_id == org_id,
                        WorkspaceMembership.workspace_id == workspace_id,
                    )
                    .exists(),
                ),
            )
        )
        return await cls.page(request, condition)

    @classmethod
    async def page_candidates_for_workspace(cls, org_id: UUID, workspace_id: UUID, request: PageQuery) -> PageSlice[Self]:
        return await cls.page(
            request,
            col(cls.id).in_(select(OrgMembership.user_id).where(OrgMembership.org_id == org_id)),
            ~select(WorkspaceMembership.user_id)
            .where(WorkspaceMembership.user_id == cls.id, WorkspaceMembership.workspace_id == workspace_id)
            .exists(),
        )

    @classmethod
    async def page_inference_key_owners(cls, principal_id: UUID, org_id: UUID, include_managed: bool, request: PageQuery) -> PageSlice[Self]:
        condition = col(cls.id) == principal_id
        if include_managed:
            condition = or_(condition, (col(cls.managing_org_id) == org_id) & col(cls.service_account).is_(True))
        return await cls.page(
            request,
            condition,
        )

    @classmethod
    async def membership_counts(cls, user_ids: tuple[UUID, ...]) -> dict[UUID, int]:
        if not user_ids:
            return {}
        query = select(OrgMembership.user_id, func.count()).where(col(OrgMembership.user_id).in_(user_ids)).group_by(col(OrgMembership.user_id))
        return {result[0]: int(result[1]) for result in (await current_session().execute(query)).all()}

    @classmethod
    async def owned_by(cls, org_id: UUID, user_id: UUID) -> Self:
        user = await cls.find_by_id(user_id)
        if user is None or user.managing_org_id != org_id:
            raise NotOwnedError
        return user

    @classmethod
    async def instance_service_account(cls, user_id: UUID) -> Self | None:
        return await cls.first(cls.id == user_id, col(cls.service_account).is_(True), col(cls.managing_org_id).is_(None))

    @classmethod
    async def instance_claimed(cls) -> bool:
        return await cls.first(cls.instance_role == InstanceRole.owner) is not None

    @classmethod
    async def _lock_instance_owners(cls) -> tuple[UUID, ...]:
        await current_session().execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _INSTANCE_OWNER_LOCK})
        query = select(cls.id).where(cls.instance_role == InstanceRole.owner).order_by(col(cls.id))
        return tuple((await current_session().execute(query)).scalars().all())

    @classmethod
    async def reserve_unclaimed_instance(cls) -> bool:
        """Return whether the transaction may create authority before the first owner exists."""
        if await cls.instance_claimed():
            return False
        return not await cls._lock_instance_owners()

    @staticmethod
    def _refuse_last_owner_removal(owner_ids: tuple[UUID, ...], user_id: UUID) -> None:
        if owner_ids == (user_id,):
            raise LastInstanceOwnerError

    async def delete_with_contents(self) -> None:
        """Delete the user with the entities they own that are theirs alone: identities, sessions, and management keys.

        The sibling of Org.delete_with_contents and Workspace.delete_with_contents. Everything else a
        user touches outlives them, so the route refuses rather than cascading: a membership is the
        org's decision, a personal org is a tenant, an inference key belongs to its workspace.
        """
        from control_plane import models  # noqa: PLC0415 auth_identity imports user, so the two only meet at call time

        owner_ids = await self._lock_instance_owners()
        self._refuse_last_owner_removal(owner_ids, self.id)
        for owned in (models.AuthIdentity, models.AuthSession):
            for record in await owned.find(owned.user_id == self.id):
                await record.delete()
        await models.ManagementKey.delete_scoped(models.ManagementKey.user_id == self.id)
        await models.InferenceKey.delete_owned_by(self.id)
        await models.PlaygroundSession.delete_owned_by(self.id)
        await self.delete()

    @classmethod
    async def change_instance_role(cls, user_id: UUID, instance_role: InstanceRole | None) -> Self | None:
        owner_ids = await cls._lock_instance_owners()
        user = await cls.find_by_id(user_id)
        if user is None:
            return None
        if user.managing_org_id is not None:
            raise ManagedServiceAccountInstanceRoleError
        if user.instance_role == InstanceRole.owner and instance_role != InstanceRole.owner:
            cls._refuse_last_owner_removal(owner_ids, user_id)
        user.instance_role = instance_role
        return await user.save()

    @classmethod
    def new_service_account(cls, name: str, instance_role: InstanceRole | None = None, managing_org_id: UUID | None = None) -> Self:
        """Machine principal with a derived unique email; the caller saves it and adds memberships."""
        return cls(
            email=f"{slugify(name)}-{uuid4().hex[:8]}@{SERVICE_ACCOUNT_EMAIL_DOMAIN}",
            name=name,
            instance_role=instance_role,
            service_account=True,
            managing_org_id=managing_org_id,
        )


class ServiceAccountNameIn(RequestModel):
    name: str = Field(
        description="Display name for the service account",
        min_length=1,
        max_length=200,
    )

    @field_validator("name")
    @classmethod
    def name_yields_an_email_local_part(cls, v: str) -> str:
        if not slugify(v):
            msg = "name must contain at least one letter or digit"
            raise ValueError(msg)
        return v


class InstanceRoleIn(RequestModel):
    instance_role: InstanceRole | None = Field(description="Instance-wide role to assign, or null to remove instance-wide access")


class ServiceAccountIn(ServiceAccountNameIn):
    instance_role: InstanceRole | None = Field(default=None, description="Optional instance-wide role for the service account")


class OrgServiceAccountIn(ServiceAccountNameIn):
    management_key: ManagementKeyIn = Field(description="Initial organization-scoped management key to create for the service account")


class UserOut(RecordOut[User]):
    id: UUID
    email: str
    name: str
    instance_role: str | None
    service_account: bool
    managing_org_id: UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    org_count: int

    api_extra: ClassVar[frozenset[str]] = frozenset({"org_count"})


class OrgServiceAccountCreatedOut(BaseModel):
    service_account: UserOut
    membership: MembershipOut
    management_key: ManagementKeyCreatedOut
