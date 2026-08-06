from __future__ import annotations

from datetime import datetime  # noqa: TC003 pydantic resolves field annotations at runtime
from typing import ClassVar, Literal

from pydantic import BaseModel
from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.base import Record
from control_plane.models.mixins import OrgOwned, Tombstonable
from control_plane.schemas import ApiOut


@audited
class ApiKey(Record, OrgOwned, Tombstonable, table=True):
    id: str = Field(primary_key=True)
    org_id: str = Field(foreign_key="org.id")
    user_id: str = Field(foreign_key="user.id")
    token_hash: str = Field(unique=True)
    disabled: bool = False

    api_hidden: ClassVar[frozenset[str]] = frozenset({"token_hash"})
    api_readonly: ClassVar[frozenset[str]] = frozenset({"id", "user_id", "disabled"})


class ApiKeyOut(ApiOut):
    id: str
    org_id: str
    user_id: str
    disabled: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class KeyOut(BaseModel):
    key_id: str
    token: str


class KeyRevokedOut(BaseModel):
    key_id: str
    status: Literal["revoked"]
