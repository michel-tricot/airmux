from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator
from pydantic import Field as PydanticField
from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, col

from control_plane.authz import Boundary, Permission, Target
from control_plane.models.audit import audited
from control_plane.models.common import Identified, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut, RequestModel

if TYPE_CHECKING:
    from sqlalchemy.engine.interfaces import Dialect
    from sqlalchemy.sql.elements import ColumnElement

AccessKeyStatus = Literal["active", "expired", "revoked"]


class PermissionList(TypeDecorator[list[Permission]]):
    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: list[Permission] | None, dialect: Dialect) -> list[str] | None:  # noqa: ARG002 SQLAlchemy names this override parameter
        return [str(permission) for permission in value] if value is not None else None

    def process_result_value(self, value: list[str] | None, dialect: Dialect) -> list[Permission] | None:  # noqa: ARG002 SQLAlchemy names this override parameter
        return [Permission(permission) for permission in value] if value is not None else None


@audited
class AccessKey(Record, Identified, Tombstonable, table=True):
    __table_args__: ClassVar = (
        CheckConstraint("workspace_id IS NULL OR org_id IS NOT NULL", name="access_key_workspace_needs_org"),
        ForeignKeyConstraint(["workspace_id", "org_id"], ["workspace.id", "workspace.org_id"]),
    )

    user_id: UUID = Field(foreign_key="user.id")
    org_id: UUID | None = Field(default=None, foreign_key="org.id")
    workspace_id: UUID | None = None
    parent_id: UUID | None = Field(default=None, foreign_key="access_key.id")
    token_hash: str = Field(unique=True)
    prefix: str
    permissions: list[Permission] = Field(sa_type=PermissionList)
    label: str
    expires_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    revoked_at: datetime | None = Field(default=None, sa_type=UTCDateTime)

    api_hidden: ClassVar[frozenset[str]] = frozenset({"token_hash"})

    @property
    def boundary(self) -> Boundary:
        if self.workspace_id is not None:
            return Boundary.workspace
        return Boundary.org if self.org_id is not None else Boundary.instance

    @property
    def target(self) -> Target:
        return Target(level=self.boundary, org_id=self.org_id, workspace_id=self.workspace_id)

    def status(self, now: datetime) -> AccessKeyStatus:
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at is not None and self.expires_at <= now:
            return "expired"
        return "active"

    @classmethod
    async def retire_for_client(cls, user_id: UUID, target: Target, label: str, revoked_at: datetime) -> list[Self]:
        keys = await cls.find(
            cls.user_id == user_id,
            cls.org_id == target.org_id,
            cls.workspace_id == target.workspace_id,
            cls.label == label,
            col(cls.revoked_at).is_(None),
        )
        for key in keys:
            key.revoked_at = revoked_at
            await key.save()
        return keys

    async def revoke_with_descendants(self, revoked_at: datetime) -> None:
        pending: list[AccessKey] = [self]
        seen: set[UUID] = set()
        while pending:
            key = pending.pop()
            if key.id in seen:
                continue
            seen.add(key.id)
            pending.extend(await AccessKey.find(AccessKey.parent_id == key.id))
            if key.revoked_at is None:
                key.revoked_at = revoked_at
                await key.save()

    async def delete_with_descendants(self) -> None:
        for child in await AccessKey.find(AccessKey.parent_id == self.id):
            await child.delete_with_descendants()
        await self.delete()

    @classmethod
    async def delete_scoped(cls, *conditions: ColumnElement[bool] | bool) -> None:
        keys = await cls.find(*conditions)
        key_ids = {key.id for key in keys}
        for key in keys:
            if key.parent_id not in key_ids:
                await key.delete_with_descendants()


class AccessKeyOut(RecordOut[AccessKey]):
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
    boundary: Boundary
    status: AccessKeyStatus

    api_extra: ClassVar[frozenset[str]] = frozenset({"boundary", "status"})


class AccessKeyMintedOut(BaseModel):
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
    boundary: Boundary
    status: AccessKeyStatus
    token: str


class AccessKeyRevokedOut(BaseModel):
    id: UUID
    status: Literal["revoked"]
    revoked_at: datetime


class AccessKeyIn(RequestModel):
    label: str = PydanticField(description="Where this key lives, such as ci, laptop, or data-plane", min_length=1, max_length=80)
    user_id: UUID | None = PydanticField(default=None, description="Principal the key authenticates; defaults to the acting principal")
    org_id: UUID | None = PydanticField(default=None, description="Organization boundary; omit with workspace_id for instance authority")
    workspace_id: UUID | None = PydanticField(default=None, description="Workspace boundary; requires org_id")
    permissions: list[Permission] = PydanticField(min_length=1, description="Explicit maximum permissions carried by the key")
    expires_at: datetime | None = None

    @field_validator("permissions")
    @classmethod
    def unique_permissions(cls, permissions: list[Permission]) -> list[Permission]:
        if len(permissions) != len(set(permissions)):
            msg = "permissions must not contain duplicates"
            raise ValueError(msg)
        return sorted(permissions, key=str)

    @field_validator("expires_at")
    @classmethod
    def aware_expiry(cls, expires_at: datetime | None) -> datetime | None:
        if expires_at is None:
            return None
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            msg = "expires_at must include a timezone"
            raise ValueError(msg)
        return expires_at.astimezone(UTC)

    @model_validator(mode="after")
    def valid_boundary(self) -> Self:
        if self.workspace_id is not None and self.org_id is None:
            msg = "workspace_id requires org_id"
            raise ValueError(msg)
        return self

    @property
    def target(self) -> Target:
        org_id = self.org_id
        if self.workspace_id is not None:
            if org_id is None:
                msg = "workspace_id requires org_id"
                raise ValueError(msg)
            return Target.workspace(org_id, self.workspace_id)
        return Target.org(org_id) if org_id is not None else Target.instance()
