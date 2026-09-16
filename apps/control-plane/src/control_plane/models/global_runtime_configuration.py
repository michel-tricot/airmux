from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Field, col, select

from control_plane.db import current_session
from control_plane.models.common.base import Record


class GlobalRuntimeConfiguration(Record, table=True):
    id: int = Field(default=1, primary_key=True)
    desired_revision: int = 0

    @classmethod
    async def desired(cls) -> int:
        configuration = await current_session().get(cls, 1)
        return configuration.desired_revision if configuration is not None else 0

    @classmethod
    async def advance(cls, revision: int) -> None:
        insert = pg_insert(cls).values(id=1, desired_revision=revision)
        statement = insert.on_conflict_do_update(
            index_elements=["id"], set_={"desired_revision": func.greatest(col(cls.desired_revision), insert.excluded.desired_revision)}
        )
        await current_session().execute(statement)

    @classmethod
    async def lock_for_publication(cls) -> None:
        configuration = (await current_session().execute(select(cls).where(cls.id == 1).with_for_update())).scalar_one_or_none()
        if configuration is None:
            msg = "global runtime configuration is not initialized"
            raise RuntimeError(msg)
