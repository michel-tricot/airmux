from __future__ import annotations

from datetime import datetime  # noqa: TC003 pydantic resolves field annotations at runtime
from typing import ClassVar, Literal

from pydantic import BaseModel
from sqlalchemy import JSON
from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.base import Record
from control_plane.models.mixins import OrgOwned, Tombstonable
from control_plane.schemas import ApiCreate, ApiOut


@audited
class ApiKey(Record, OrgOwned, Tombstonable, table=True):
    id: str = Field(primary_key=True)
    org_id: str = Field(foreign_key="org.id")
    allowed_models: list[str] = Field(default_factory=list, sa_type=JSON)
    disabled: bool = False

    api_readonly: ClassVar[frozenset[str]] = frozenset({"id", "disabled"})


class ApiKeyCreate(ApiCreate):
    allowed_models: list[str] = Field(default=["*"], description="Model ids this key may call, * for all")


class ApiKeyOut(ApiOut):
    id: str
    org_id: str
    allowed_models: list[str]
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
