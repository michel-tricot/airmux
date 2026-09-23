from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import Depends
from pydantic import Field, StringConstraints

from control_plane.db import current_session
from control_plane.models.common.wire import RequestModel

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import InstrumentedAttribute, Mapped
    from sqlalchemy.sql import Select

MAX_CURSOR_LENGTH = 512

type CursorToken = Annotated[str, StringConstraints(min_length=1, max_length=MAX_CURSOR_LENGTH, pattern=r"^[A-Za-z0-9_-]+$")]
type CursorAnchor = UUID | int
type Direction = Literal["asc", "desc"]


class InvalidCursorError(ValueError):
    def __init__(self) -> None:
        super().__init__("invalid cursor")


class PageQuery(RequestModel):
    cursor: CursorToken | None = None
    limit: int = Field(default=50, ge=1, le=200)


PageDep = Annotated[PageQuery, Depends()]


@dataclass(frozen=True)
class PageSlice[T]:
    items: tuple[T, ...]
    next_cursor: CursorToken | None


def encode_cursor(value: CursorAnchor) -> CursorToken:
    return base64.urlsafe_b64encode(str(value).encode()).decode().rstrip("=")


def decode_cursor[T: CursorAnchor](token: str, parse: Callable[[str], T]) -> T:
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True).decode()
        return parse(raw)
    except (UnicodeDecodeError, binascii.Error, ValueError, OverflowError) as error:
        raise InvalidCursorError from error


async def keyset_page[T](
    statement: Select[tuple[T]],
    request: PageQuery,
    column: Mapped[Any],
    parse: Callable[[str], CursorAnchor],
    direction: Direction = "desc",
) -> PageSlice[T]:
    if request.cursor is not None:
        anchor = decode_cursor(request.cursor, parse)
        statement = statement.where(column > anchor if direction == "asc" else column < anchor)
    order = column.asc() if direction == "asc" else column.desc()
    items = tuple((await current_session().execute(statement.order_by(order).limit(request.limit + 1))).scalars().all())
    visible = items[: request.limit]
    column_name = cast("InstrumentedAttribute[CursorAnchor]", column).key
    next_cursor = encode_cursor(getattr(visible[-1], column_name)) if len(items) > request.limit else None
    return PageSlice(items=visible, next_cursor=next_cursor)
