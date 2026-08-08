from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal
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

    api_hidden: ClassVar[frozenset[str]] = frozenset({"token_hash"})
    api_readonly: ClassVar[frozenset[str]] = frozenset({"scopes"})


class ManagementKeyOut(RecordOut[ManagementKey]):
    id: UUID
    org_id: UUID | None
    user_id: UUID
    revoked: bool
    scopes: list[str] | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ManagementKeyMintedOut(BaseModel):
    id: UUID
    org_id: UUID | None
    user_id: UUID
    scopes: list[str] | None
    token: str


class ManagementKeyRevokedOut(BaseModel):
    id: UUID
    status: Literal["revoked"]


class ManagementKeyIn(BaseModel):
    org_id: UUID | None = Field(None, description="Org to scope the token to; omit for an instance token, instance admins only")
    scopes: list[Scope] | None = Field(None, description="Restrict the token to these scopes; omit for the user's full authority")
