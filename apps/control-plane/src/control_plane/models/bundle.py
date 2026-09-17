from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Self
from uuid import UUID

from sqlalchemy import Index
from sqlmodel import Field, col, select

from control_plane.db import current_session
from control_plane.models.common import KeyColumn, Keyset, OrgOwned, PageQuery, PageSlice, keyset_page
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut


class Bundle(Record, OrgOwned, table=True):
    __table_args__: ClassVar = (Index("bundle_org_version_key", "org_id", "version", unique=True),)

    id: UUID = Field(primary_key=True)
    org_id: UUID = Field(foreign_key="org.id")
    version: int
    issued_at: datetime = Field(sa_type=UTCDateTime)
    configuration_revision: int = 0
    payload: str

    api_hidden: ClassVar[frozenset[str]] = frozenset({"configuration_revision", "payload"})

    @classmethod
    async def latest_refs_per_org(cls, org_id: UUID | None) -> list[tuple[UUID, UUID]]:
        query = select(cls.org_id, cls.id)
        if org_id is not None:
            query = query.where(cls.org_id == org_id)
        query = query.distinct(col(cls.org_id)).order_by(col(cls.org_id), col(cls.version).desc())
        return [(bundle_org_id, bundle_id) for bundle_org_id, bundle_id in (await current_session().execute(query)).all()]

    @classmethod
    async def page_for_org(cls, org_id: UUID, request: PageQuery) -> PageSlice[Self]:
        return await keyset_page(
            select(cls).where(cls.org_id == org_id),
            request,
            Keyset(model=cls, partition_columns=("org_id",), columns=(KeyColumn(col(cls.version), "asc", "int"),)),
        )


class BundleOut(RecordOut[Bundle]):
    id: UUID
    org_id: UUID
    version: int
    issued_at: datetime
