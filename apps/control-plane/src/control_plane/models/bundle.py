from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from sqlalchemy import BigInteger, UniqueConstraint
from sqlmodel import Field, col, select

from control_plane.db import current_session
from control_plane.models.common import OrgOwned
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime


class Bundle(Record, OrgOwned, table=True):
    __table_args__ = (
        UniqueConstraint("org_id", "version", name="bundle_org_id_version_key"),
        UniqueConstraint("org_id", "global_generation", "org_generation", name="bundle_org_generation_key"),
    )

    id: UUID = Field(primary_key=True)
    org_id: UUID = Field(foreign_key="org.id", ondelete="CASCADE")
    version: int
    issued_at: datetime = Field(sa_type=UTCDateTime)
    global_generation: int = Field(sa_type=BigInteger)
    org_generation: int = Field(sa_type=BigInteger)
    payload: str

    api_hidden: ClassVar[frozenset[str]] = frozenset({"global_generation", "org_generation", "payload"})

    @classmethod
    async def latest_refs_per_org(cls, org_id: UUID | None) -> list[tuple[UUID, UUID]]:
        from control_plane.models.bundle_state import BundleState  # noqa: PLC0415 bundle transport follows the publication pointer

        query = select(cls.org_id, cls.id).join(BundleState, col(BundleState.current_bundle_id) == col(cls.id))
        if org_id is not None:
            query = query.where(cls.org_id == org_id)
        query = query.order_by(col(cls.org_id))
        return [(bundle_org_id, bundle_id) for bundle_org_id, bundle_id in (await current_session().execute(query)).all()]

    @classmethod
    async def current(cls, org_id: UUID | None) -> Bundle | None:
        from control_plane.models.bundle_state import BundleState  # noqa: PLC0415 bundle transport follows the publication pointer

        query = select(cls).join(BundleState, col(BundleState.current_bundle_id) == col(cls.id))
        if org_id is not None:
            query = query.where(cls.org_id == org_id)
        return (await current_session().execute(query.order_by(col(cls.issued_at).desc(), col(cls.id).desc()).limit(1))).scalar_one_or_none()
