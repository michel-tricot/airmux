from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from sqlmodel import Field, col, select

from control_plane.db import current_session
from control_plane.models.common import OrgOwned
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut


class Bundle(Record, OrgOwned, table=True):
    id: UUID = Field(primary_key=True)
    org_id: UUID = Field(foreign_key="org.id")
    version: int
    issued_at: datetime = Field(sa_type=UTCDateTime)
    configuration_revision: int = 0
    payload: str
    signature: str
    signing_key_id: str

    api_hidden: ClassVar[frozenset[str]] = frozenset({"configuration_revision", "payload", "signature"})

    @classmethod
    async def latest_per_org(cls, org_id: UUID | None) -> list[Bundle]:
        query = select(cls)
        if org_id is not None:
            query = query.where(cls.org_id == org_id)
        query = query.distinct(col(cls.org_id)).order_by(col(cls.org_id), col(cls.version).desc())
        return list((await current_session().execute(query)).scalars())


class BundleOut(RecordOut[Bundle]):
    id: UUID
    org_id: UUID
    version: int
    issued_at: datetime
    signing_key_id: str
