from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from sqlmodel import SQLModel, select

from control_plane.db import current_session

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement
    from sqlalchemy.orm import Mapped

    type OrderBy = ColumnElement[Any] | Mapped[Any]


class NotOwnedError(Exception):
    pass


class Record(SQLModel):
    @classmethod
    async def get(cls, ident: object) -> Self | None:
        return await current_session().get(cls, ident)

    @classmethod
    async def find(
        cls, *conditions: ColumnElement[bool] | bool, order_by: OrderBy | tuple[OrderBy, ...] | None = None, limit: int | None = None
    ) -> list[Self]:
        query = select(cls).where(*conditions)
        if order_by is not None:
            query = query.order_by(*(order_by if isinstance(order_by, tuple) else (order_by,)))
        if limit is not None:
            query = query.limit(limit)
        return list((await current_session().execute(query)).scalars().all())

    @classmethod
    async def first(cls, *conditions: ColumnElement[bool] | bool, order_by: OrderBy | tuple[OrderBy, ...] | None = None) -> Self | None:
        rows = await cls.find(*conditions, order_by=order_by, limit=1)
        return rows[0] if rows else None

    async def save(self) -> Self:
        session = current_session()
        session.add(self)
        await session.flush()
        return self

    async def delete(self) -> None:
        session = current_session()
        await session.delete(self)
        await session.flush()


class OrgOwned(Record):
    org_id: str

    @classmethod
    async def owned_by(cls, org: str, ident: object) -> Self:
        row = await cls.get(ident)
        if row is None or row.org_id != org:
            raise NotOwnedError
        return row
