from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel, field_validator
from pydantic import Field as PydanticField
from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, col

from control_plane.authz import Permission, Scope
from control_plane.models.audit import audited
from control_plane.models.common import Identified, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut, RequestModel

if TYPE_CHECKING:
    from sqlalchemy.engine.interfaces import Dialect
    from sqlalchemy.sql.elements import ColumnElement

ManagementKeyStatus = Literal["active", "expired", "revoked"]


class PermissionList(TypeDecorator[list[Permission]]):
    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: list[Permission] | None, dialect: Dialect) -> list[str] | None:  # noqa: ARG002 SQLAlchemy names this override parameter
        return [str(permission) for permission in value] if value is not None else None

    def process_result_value(self, value: list[str] | None, dialect: Dialect) -> list[Permission] | None:  # noqa: ARG002 SQLAlchemy names this override parameter
        return [Permission(permission) for permission in value] if value is not None else None


@audited
class ManagementKey(Record, Identified, Tombstonable, table=True):
    __table_args__: ClassVar = (
        CheckConstraint("workspace_id IS NULL OR org_id IS NOT NULL", name="management_key_workspace_needs_org"),
        ForeignKeyConstraint(["workspace_id", "org_id"], ["workspace.id", "workspace.org_id"]),
    )

    user_id: UUID = Field(foreign_key="user.id")
    org_id: UUID | None = Field(default=None, foreign_key="org.id")
    workspace_id: UUID | None = None
    parent_id: UUID | None = Field(default=None, foreign_key="management_key.id")
    token_hash: str = Field(unique=True)
    prefix: str
    permissions: list[Permission] = Field(sa_type=PermissionList)
    label: str
    expires_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    revoked_at: datetime | None = Field(default=None, sa_type=UTCDateTime)

    api_hidden: ClassVar[frozenset[str]] = frozenset({"token_hash"})

    @property
    def scope(self) -> Scope:
        if self.workspace_id is not None:
            org_id = self.org_id
            if org_id is None:
                msg = "workspace management key has no organization"
                raise ValueError(msg)
            return Scope.workspace(org_id, self.workspace_id)
        return Scope.org(self.org_id) if self.org_id is not None else Scope.instance()

    def status(self, now: datetime) -> ManagementKeyStatus:
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at is not None and self.expires_at <= now:
            return "expired"
        return "active"

    @classmethod
    async def retire_replaced(cls, key_id: UUID, user_id: UUID, scope: Scope, revoked_at: datetime) -> Self | None:
        key = await cls.first(
            cls.id == key_id,
            cls.user_id == user_id,
            cls.org_id == scope.org_id,
            cls.workspace_id == scope.workspace_id,
            col(cls.revoked_at).is_(None),
        )
        if key is not None:
            await key.revoke_with_descendants(revoked_at)
        return key

    async def revoke_with_descendants(self, revoked_at: datetime) -> None:
        pending: list[ManagementKey] = [self]
        seen: set[UUID] = set()
        while pending:
            key = pending.pop()
            if key.id in seen:
                continue
            seen.add(key.id)
            pending.extend(await ManagementKey.find(ManagementKey.parent_id == key.id))
            if key.revoked_at is None:
                key.revoked_at = revoked_at
                await key.save()

    async def delete_with_descendants(self) -> None:
        for child in await ManagementKey.find(ManagementKey.parent_id == self.id):
            await child.delete_with_descendants()
        await self.delete()

    @classmethod
    async def delete_scoped(cls, *conditions: ColumnElement[bool] | bool) -> None:
        keys = await cls.find(*conditions)
        key_ids = {key.id for key in keys}
        for key in keys:
            if key.parent_id not in key_ids:
                await key.delete_with_descendants()


class ManagementKeyOut(RecordOut[ManagementKey]):
    id: UUID
    user_id: UUID
    org_id: UUID | None
    workspace_id: UUID | None
    parent_id: UUID | None
    prefix: str
    permissions: list[Permission]
    label: str
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    scope: Scope
    status: ManagementKeyStatus

    api_extra: ClassVar[frozenset[str]] = frozenset({"scope", "status"})


class ManagementKeyCreatedOut(BaseModel):
    id: UUID
    user_id: UUID
    org_id: UUID | None
    workspace_id: UUID | None
    parent_id: UUID | None
    prefix: str
    permissions: list[Permission]
    label: str
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    scope: Scope
    status: ManagementKeyStatus
    token: str


class ManagementKeyRevokedOut(BaseModel):
    id: UUID
    status: Literal["revoked"]
    revoked_at: datetime


class ManagementKeyPermissionsIn(RequestModel):
    permissions: list[Permission] = PydanticField(min_length=1, description="Explicit maximum permissions carried by the key")

    @field_validator("permissions")
    @classmethod
    def unique_permissions(cls, permissions: list[Permission]) -> list[Permission]:
        if len(permissions) != len(set(permissions)):
            msg = "permissions must not contain duplicates"
            raise ValueError(msg)
        return sorted(permissions, key=str)


class ManagementKeyIn(ManagementKeyPermissionsIn):
    label: str = PydanticField(description="Where this key lives, such as ci, laptop, or data-plane", min_length=1, max_length=80)
    expires_at: datetime | None = PydanticField(default=None, description="Optional expiration timestamp with a timezone")

    @field_validator("expires_at")
    @classmethod
    def aware_expiry(cls, expires_at: datetime | None) -> datetime | None:
        if expires_at is None:
            return None
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            msg = "expires_at must include a timezone"
            raise ValueError(msg)
        return expires_at.astimezone(UTC)
