from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field

from control_plane.models.base import OrgOwned


class Bundle(OrgOwned, table=True):
    id: UUID = Field(primary_key=True)
    org_id: str = Field(foreign_key="org.id")
    version: int
    issued_at: datetime
    expires_at: datetime
    payload: str
    signature: str
    signing_key_id: str
