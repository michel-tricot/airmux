from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, col, select

from control_plane.db import current_session
from control_plane.models.common import OrgOwned
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut


class Bundle(Record, OrgOwned, table=True):
    __table_args__ = (
        UniqueConstraint("org_id", "version", name="bundle_org_id_version_key"),
        UniqueConstraint("org_id", "configuration_revision", name="bundle_org_id_configuration_revision_key"),
    )

    id: UUID = Field(primary_key=True)
    org_id: UUID = Field(foreign_key="org.id", ondelete="CASCADE")
    version: int
    issued_at: datetime = Field(sa_type=UTCDateTime)
    configuration_revision: int
    payload: str

    api_hidden: ClassVar[frozenset[str]] = frozenset({"configuration_revision", "payload"})

    @classmethod
    async def latest_refs_per_org(cls, org_id: UUID | None) -> list[tuple[UUID, UUID]]:
        query = select(cls.org_id, cls.id)
        if org_id is not None:
            query = query.where(cls.org_id == org_id)
        query = query.distinct(col(cls.org_id)).order_by(col(cls.org_id), col(cls.version).desc())
        return [(bundle_org_id, bundle_id) for bundle_org_id, bundle_id in (await current_session().execute(query)).all()]


class BundleOut(RecordOut[Bundle]):
    id: UUID
    org_id: UUID
    version: int
    issued_at: datetime
