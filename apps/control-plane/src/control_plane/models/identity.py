from __future__ import annotations

import re
from typing import Self
from uuid import uuid4

from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.base import Record
from control_plane.models.tombstone import Tombstonable

SERVICE_ACCOUNT_EMAIL_DOMAIN = "airbytesvcaccount.ai"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@audited
class User(Record, Tombstonable, table=True):
    id: str = Field(primary_key=True)
    email: str = Field(unique=True)
    name: str
    instance_admin: bool = False
    service_account: bool = False

    @classmethod
    def new_service_account(cls, name: str, *, instance_admin: bool = False) -> Self:
        """Machine principal with a derived unique email; the caller saves it and adds memberships."""
        return cls(
            id=f"u-{uuid4().hex[:8]}",
            email=f"{slug(name)}-{uuid4().hex[:8]}@{SERVICE_ACCOUNT_EMAIL_DOMAIN}",
            name=name,
            instance_admin=instance_admin,
            service_account=True,
        )


@audited
class OrgMembership(Record, Tombstonable, table=True):
    user_id: str = Field(primary_key=True, foreign_key="user.id")
    org_id: str = Field(primary_key=True, foreign_key="org.id")


@audited
class MgmtToken(Record, Tombstonable, table=True):
    id: str = Field(primary_key=True)
    org_id: str | None = None
    user_id: str | None = Field(default=None, foreign_key="user.id")
    revoked: bool = False
