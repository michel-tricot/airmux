from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import JSON
from sqlmodel import Field

from control_plane.authz import Scope
from control_plane.models.audit import audited
from control_plane.models.common import Identified, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordOut


@audited
class ManagementKey(Record, Identified, Tombstonable, table=True):
    org_id: UUID | None = None
    user_id: UUID = Field(foreign_key="user.id")
    token_hash: str = Field(unique=True)
    revoked: bool = False
    scopes: list[str] | None = Field(default=None, sa_type=JSON)
    label: str

    api_hidden: ClassVar[frozenset[str]] = frozenset({"token_hash"})
    api_readonly: ClassVar[frozenset[str]] = frozenset({"scopes", "label"})

    @classmethod
    async def retire_for_client(cls, user_id: UUID, org_id: UUID, label: str) -> list[Self]:
        """Revoke the live keys this client label holds for the org, so a re-login replaces its key instead of accumulating."""
        keys = [k for k in await cls.find(cls.user_id == user_id, cls.org_id == org_id, cls.label == label) if not k.revoked]
        for key in keys:
            key.revoked = True
            await key.save()
        return keys


class ManagementKeyOut(RecordOut[ManagementKey]):
    id: UUID
    org_id: UUID | None
    user_id: UUID
    revoked: bool
    scopes: list[str] | None
    label: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ManagementKeyMintedOut(BaseModel):
    id: UUID
    org_id: UUID | None
    user_id: UUID
    scopes: list[str] | None
    label: str
    token: str


class ManagementKeyRevokedOut(BaseModel):
    id: UUID
    status: Literal["revoked"]


class ManagementKeyIn(BaseModel):
    label: str = Field(description="Where this token lives, e.g. ci or laptop; shown in listings", min_length=1, max_length=80)
    org_id: UUID | None = Field(None, description="Org to scope the token to; omit for an instance token, instance admins only")
    scopes: list[Scope] | None = Field(None, description="Restrict the token to these scopes; omit for the user's full authority")
