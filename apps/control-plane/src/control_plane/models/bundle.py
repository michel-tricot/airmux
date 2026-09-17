from __future__ import annotations

from uuid import UUID

from sqlalchemy import BigInteger, UniqueConstraint
from sqlmodel import Field, col, select

from control_plane.db import current_session
from control_plane.models.common import OrgOwned
from control_plane.models.common.base import Record


class Bundle(Record, OrgOwned, table=True):
    __table_args__ = (UniqueConstraint("org_id", "global_generation", "org_generation", name="bundle_org_generation_key"),)

    id: UUID = Field(primary_key=True)
    org_id: UUID = Field(foreign_key="org.id", ondelete="CASCADE")
    global_generation: int = Field(sa_type=BigInteger)
    org_generation: int = Field(sa_type=BigInteger)
    payload: str

    @classmethod
    async def latest_refs_per_org(cls, org_id: UUID | None) -> list[tuple[UUID, UUID]]:
        from control_plane.models.bundle_state import BundleState  # noqa: PLC0415 bundle transport follows the publication pointer

        query = select(cls.org_id, cls.id).join(BundleState, col(BundleState.current_bundle_id) == col(cls.id))
        if org_id is not None:
            query = query.where(cls.org_id == org_id)
        query = query.order_by(col(cls.org_id))
        return [(bundle_org_id, bundle_id) for bundle_org_id, bundle_id in (await current_session().execute(query)).all()]
