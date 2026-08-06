from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel
from sqlmodel import Field

from control_plane.models.base import Record
from control_plane.models.mixins import OrgOwned
from control_plane.schemas import ApiOut


class Bundle(Record, OrgOwned, table=True):
    id: UUID = Field(primary_key=True)
    org_id: str = Field(foreign_key="org.id")
    version: int
    issued_at: datetime
    expires_at: datetime
    payload: str
    signature: str
    signing_key_id: str

    api_hidden: ClassVar[frozenset[str]] = frozenset({"payload", "signature"})


class BundleOut(ApiOut):
    id: UUID
    org_id: str
    version: int
    issued_at: datetime
    expires_at: datetime
    signing_key_id: str


class CompileOut(BaseModel):
    bundle_id: str
    version: int
