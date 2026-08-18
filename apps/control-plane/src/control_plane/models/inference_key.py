from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import ForeignKeyConstraint
from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.common import Identified, OrgOwned, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordOut, RequestModel
from control_plane.models.runtime_configuration import runtime_configured


@audited
@runtime_configured(scope="org", columns=("org_id", "workspace_id", "token_hash", "revoked"))
class InferenceKey(Record, Identified, OrgOwned, Tombstonable, table=True):
    """org_id stays denormalized beside workspace_id so the compiler collects an org's keys in one
    query and owned_by keeps working; the composite foreign key keeps the pair from disagreeing."""

    __table_args__: ClassVar = (ForeignKeyConstraint(["workspace_id", "org_id"], ["workspace.id", "workspace.org_id"]),)

    org_id: UUID = Field(foreign_key="org.id")
    workspace_id: UUID
    user_id: UUID = Field(foreign_key="user.id")
    token_hash: str = Field(unique=True)
    prefix: str
    revoked: bool = False
    label: str

    api_hidden: ClassVar[frozenset[str]] = frozenset({"token_hash"})
    api_readonly: ClassVar[frozenset[str]] = frozenset({"workspace_id", "user_id", "revoked", "label", "prefix"})


class InferenceKeyIn(RequestModel):
    label: str = Field(description="What this key is for, e.g. staging or the calling app; shown in listings", min_length=1, max_length=80)


class InferenceKeyOut(RecordOut[InferenceKey]):
    id: UUID
    org_id: UUID
    workspace_id: UUID
    user_id: UUID
    revoked: bool
    label: str
    prefix: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class InferenceKeyMintedOut(BaseModel):
    id: UUID
    token: str


class InferenceKeyRevokedOut(BaseModel):
    id: UUID
    status: Literal["revoked"]
