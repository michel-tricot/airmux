from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar, Self

from sqlalchemy.orm import declared_attr
from sqlmodel import SQLModel, select

from control_plane.db import current_session


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def api_set(model: type, name: str) -> frozenset[str]:
    """Union the class's own api_* declaration with every mixin's, not first-wins like attribute lookup."""
    return frozenset().union(*(vars(base).get(name, ()) for base in model.__mro__))


def api_dispositions(model: type) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """(hidden, readonly, immutable) composed across the MRO; hidden beats readonly beats immutable, so policy can tighten but never loosen."""
    hidden = api_set(model, "api_hidden")
    readonly = api_set(model, "api_readonly") - hidden
    immutable = api_set(model, "api_immutable") - hidden - readonly
    return hidden, readonly, immutable


if TYPE_CHECKING:
    from pydantic import BaseModel
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
        records = await cls.find(*conditions, order_by=order_by, limit=1)
        return records[0] if records else None

    def apply(self, update: BaseModel) -> Self:
        """Patch the record with the fields the caller actually sent; the Update model is the mutable subset."""
        for name, value in update.model_dump(exclude_unset=True).items():
            setattr(self, name, value)
        return self

    async def save(self) -> Self:
        session = current_session()
        session.add(self)
        await session.flush()
        return self

    async def delete(self) -> None:
        session = current_session()
        await session.delete(self)
        await session.flush()
