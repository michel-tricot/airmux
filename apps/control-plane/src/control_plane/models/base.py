from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar, Self

from sqlalchemy.orm import declared_attr
from sqlmodel import SQLModel, select

from control_plane.db import current_session


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


if TYPE_CHECKING:
    from sqlalchemy import ColumnElement
    from sqlalchemy.orm import Mapped

    type OrderBy = ColumnElement[Any] | Mapped[Any]


class Record(SQLModel):
    api_hidden: ClassVar[frozenset[str]] = frozenset()
    api_readonly: ClassVar[frozenset[str]] = frozenset()
    api_immutable: ClassVar[frozenset[str]] = frozenset()

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return _snake(cls.__name__)

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
