from __future__ import annotations

from datetime import datetime  # noqa: TC003 pydantic resolves field annotations at runtime
from typing import ClassVar

from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.base import Record
from control_plane.models.mixins import Tombstonable
from control_plane.schemas import ApiCreate, ApiOut, ApiPatch


@audited
class Org(Record, Tombstonable, table=True):
    id: str = Field(primary_key=True)
    name: str

    api_immutable: ClassVar[frozenset[str]] = frozenset({"id"})


class OrgCreate(ApiCreate):
    id: str = Field(description="Org id, e.g. org-dev")
    name: str = Field("", description="Display name, defaults to the id")


class OrgPatch(ApiPatch):
    name: str | None = None


class OrgOut(ApiOut):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
