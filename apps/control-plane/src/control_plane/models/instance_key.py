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
class InstanceKey(Record, Identified, Tombstonable, table=True):
    """Instance-wide authority: the credential for the endpoints that stand above any single org."""

    user_id: UUID = Field(foreign_key="user.id")
    token_hash: str = Field(unique=True)
    revoked: bool = False
    scopes: list[str] | None = Field(default=None, sa_type=JSON)
    label: str

    api_hidden: ClassVar[frozenset[str]] = frozenset({"token_hash"})
    api_readonly: ClassVar[frozenset[str]] = frozenset({"scopes", "label"})


class InstanceKeyOut(RecordOut[InstanceKey]):
    id: UUID
    user_id: UUID
    revoked: bool
    scopes: list[str] | None
    label: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class InstanceKeyMintedOut(BaseModel):
    id: UUID
    user_id: UUID
    scopes: list[str] | None
    label: str
    token: str


class InstanceKeyRevokedOut(BaseModel):
    id: UUID
    status: Literal["revoked"]


class InstanceKeyIn(BaseModel):
    label: str = Field(description="Where this key lives, e.g. ci or a data plane; shown in listings", min_length=1, max_length=80)
    user_id: UUID | None = Field(None, description="Instance admin the key is minted for; defaults to the acting user")
    scopes: list[Scope] | None = Field(None, description="Restrict the key to these scopes; omit for the user's full authority")
