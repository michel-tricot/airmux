from __future__ import annotations

import re
from datetime import datetime
from typing import ClassVar, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, field_validator
from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.common import Identified, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordCreate, RecordOut

SERVICE_ACCOUNT_EMAIL_DOMAIN = "airbytesvcaccount.ai"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@audited
class User(Record, Identified, Tombstonable, table=True):
    email: str = Field(unique=True)
    name: str
    instance_admin: bool = False
    service_account: bool = False

    api_readonly: ClassVar[frozenset[str]] = frozenset({"service_account"})
    api_immutable: ClassVar[frozenset[str]] = frozenset({"email"})

    @classmethod
    def new_service_account(cls, name: str, *, instance_admin: bool = False) -> Self:
        """Machine principal with a derived unique email; the caller saves it and adds memberships."""
        return cls(
            email=f"{slug(name)}-{uuid4().hex[:8]}@{SERVICE_ACCOUNT_EMAIL_DOMAIN}",
            name=name,
            instance_admin=instance_admin,
            service_account=True,
        )


class UserCreate(RecordCreate[User]):
    email: str = Field(description="Unique email identifying the user")
    name: str = Field("", description="Display name, defaults to the email")
    instance_admin: bool = Field(default=False, description="Whether the user administers the whole instance")


class ServiceAccountIn(BaseModel):
    name: str = Field(description="Service account name; the email is derived as name-<id>@airbytesvcaccount.ai")
    instance_admin: bool = Field(default=False, description="Whether the service account administers the whole instance")

    @field_validator("name")
    @classmethod
    def name_yields_an_email_local_part(cls, v: str) -> str:
        if not slug(v):
            msg = "name must contain at least one letter or digit"
            raise ValueError(msg)
        return v


class UserOut(RecordOut[User]):
    id: UUID
    email: str
    name: str
    instance_admin: bool
    service_account: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    orgs: list[UUID]

    api_extra: ClassVar[frozenset[str]] = frozenset({"orgs"})
