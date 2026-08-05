from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Self

from sqlalchemy import func
from sqlalchemy.orm import declared_attr
from sqlmodel import Field, SQLModel, select

from control_plane.db import current_session


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


if TYPE_CHECKING:
    from sqlalchemy import ColumnElement
    from sqlalchemy.orm import Mapped

    type OrderBy = ColumnElement[Any] | Mapped[Any]


class NotOwnedError(Exception):
    pass


class Record(SQLModel):
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


class OrgOwned(SQLModel):
    org_id: str

    @classmethod
    async def owned_by(cls, org: str, ident: object) -> Self:
        row = await current_session().get(cls, ident)
        if row is None or row.org_id != org:
            raise NotOwnedError
        return row


class Tombstonable(SQLModel):
    """Lifecycle timestamps for every tombstonable table; models inherit these fields and never declare them.

    The database owns these values through the touch triggers in tombstone.py: updated_at is never
    null, equals created_at on creation, and refreshes on every update. deleted_at stays null under
    SQLite, which hard-deletes; trigger-based soft delete arrives with Postgres, see notes/IDEAS.md.
    The field defaults are placeholders that satisfy NOT NULL until the insert trigger overwrites them.
    """

    created_at: datetime = Field(default_factory=utcnow, sa_column_kwargs={"server_default": func.now()})
    updated_at: datetime = Field(default_factory=utcnow, sa_column_kwargs={"server_default": func.now()})
    deleted_at: datetime | None = None
