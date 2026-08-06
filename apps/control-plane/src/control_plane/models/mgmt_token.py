from __future__ import annotations

from datetime import datetime  # noqa: TC003 pydantic resolves field annotations at runtime
from typing import ClassVar, Literal

from pydantic import BaseModel
from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.base import Record
from control_plane.models.mixins import Tombstonable
from control_plane.schemas import ApiOut


@audited
class MgmtToken(Record, Tombstonable, table=True):
    id: str = Field(primary_key=True)
    org_id: str | None = None
    user_id: str = Field(foreign_key="user.id")
    token_hash: str = Field(unique=True)
    revoked: bool = False

    api_hidden: ClassVar[frozenset[str]] = frozenset({"token_hash"})


class MgmtTokenOut(ApiOut):
    id: str
    org_id: str | None
    user_id: str
    revoked: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class MintedTokenOut(BaseModel):
    token_id: str
    org_id: str | None
    user_id: str
    token: str


class TokenRevokedOut(BaseModel):
    token_id: str
    status: Literal["revoked"]


class UserTokenIn(BaseModel):
    org_id: str | None = Field(None, description="Org to scope the token to; omit for an instance token, instance admins only")
