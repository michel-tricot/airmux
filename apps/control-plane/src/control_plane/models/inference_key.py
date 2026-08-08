from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.common import Identified, OrgOwned, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordOut


@audited
class InferenceKey(Record, Identified, OrgOwned, Tombstonable, table=True):
    org_id: UUID = Field(foreign_key="org.id")
    user_id: UUID = Field(foreign_key="user.id")
    token_hash: str = Field(unique=True)
    revoked: bool = False
    label: str

    api_hidden: ClassVar[frozenset[str]] = frozenset({"token_hash"})
    api_readonly: ClassVar[frozenset[str]] = frozenset({"user_id", "revoked", "label"})


class InferenceKeyIn(BaseModel):
    label: str = Field(description="What this key is for, e.g. staging or the calling app; shown in listings", min_length=1, max_length=80)


class InferenceKeyOut(RecordOut[InferenceKey]):
    id: UUID
    org_id: UUID
    user_id: UUID
    revoked: bool
    label: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class InferenceKeyMintedOut(RecordOut[InferenceKey]):
    """The mint result: the id plus the one-time plaintext token, which is not a column and never returns again."""

    id: UUID
    token: str

    api_extra: ClassVar[frozenset[str]] = frozenset({"token"})


class InferenceKeyRevokedOut(BaseModel):
    id: UUID
    status: Literal["revoked"]
