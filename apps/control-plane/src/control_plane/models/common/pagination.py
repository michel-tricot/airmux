from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self, cast
from uuid import UUID

from fastapi import Depends
from pydantic import Field, StringConstraints
from sqlalchemy import ColumnElement, Table, UniqueConstraint, and_, inspect, or_
from sqlmodel import SQLModel

from control_plane.db import current_session
from control_plane.models.common.wire import RequestModel

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from sqlalchemy.orm import InstrumentedAttribute
    from sqlalchemy.orm.mapper import Mapper
    from sqlalchemy.sql import Select

CURSOR_VERSION = 1
MAX_CURSOR_LENGTH = 512

type CursorToken = Annotated[str, StringConstraints(min_length=1, max_length=MAX_CURSOR_LENGTH, pattern=r"^[A-Za-z0-9_-]+$")]
type CursorScalar = str | int | bool | UUID | datetime | None
type Direction = Literal["asc", "desc"]
type AnchorKind = Literal["uuid", "int", "str", "datetime"]


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

    def map[U](self, transform: Callable[[T], U]) -> PageSlice[U]:
        return PageSlice(items=tuple(transform(item) for item in self.items), next_cursor=self.next_cursor)


@dataclass(frozen=True)
class KeyColumn:
    column: InstrumentedAttribute[Any]
    direction: Direction
    kind: AnchorKind


@dataclass(frozen=True)
class Keyset[T]:
    model: type[T]
    filter_columns: tuple[str, ...]
    columns: tuple[KeyColumn, ...]

    def __post_init__(self) -> None:
        mapper = cast("Mapper[Any]", inspect(self.model))
        table = cast("Table", mapper.persist_selectable)
        required = self.filter_columns + tuple(column.column.key for column in self.columns)
        candidates = [
            (tuple(column.key for column in table.primary_key.columns), True),
            *(
                (tuple(column.key for column in constraint.columns), True)
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
            ),
            *((tuple(column.key for column in index.columns), index.unique) for index in table.indexes),
        ]
        if not any(
            candidate[: len(required)] == required or (unique and required[: len(candidate)] == candidate) for candidate, unique in candidates
        ):
            joined = ", ".join(required)
            msg = f"{table.name} needs a pagination index beginning with ({joined})"
            raise ValueError(msg)

    @property
    def namespace(self) -> str:
        mapper = cast("Mapper[Any]", inspect(self.model))
        table = cast("Table", mapper.persist_selectable)
        ordering = ",".join(f"{column.column.key}:{column.direction}:{column.kind}" for column in self.columns)
        return _digest(f"v{CURSOR_VERSION}:{table.fullname}:{ordering}")


class UUID7Pageable(SQLModel):
    @classmethod
    async def _page(
        cls,
        statement: Select[tuple[Self]],
        request: PageQuery,
        *,
        filter_columns: tuple[str, ...],
        cursor_context: Mapping[str, CursorScalar] | None = None,
        columns: tuple[KeyColumn, ...] | None = None,
    ) -> PageSlice[Self]:
        mapper = cast("Mapper[Any]", inspect(cls))
        id_column = cast("InstrumentedAttribute[UUID]", mapper.all_orm_descriptors["id"])
        return await keyset_page(
            statement,
            request,
            Keyset(model=cls, filter_columns=filter_columns, columns=columns or (KeyColumn(id_column, "asc", "uuid"),)),
            cursor_context=cursor_context,
        )


def _digest(value: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()[:18]).decode().rstrip("=")


def _context_fingerprint(context: Mapping[str, CursorScalar]) -> str:
    normalized = {
        key: value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, UUID) else value
        for key, value in sorted(context.items())
    }
    return _digest(json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def _serialize_anchor(value: object, kind: AnchorKind) -> str:
    if kind == "uuid" and isinstance(value, UUID):
        return str(value)
    if kind == "int" and isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if kind == "str" and isinstance(value, str):
        return value
    if kind == "datetime" and isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None:
        return value.isoformat()
    raise InvalidCursorError


def _parse_anchor(value: object, kind: AnchorKind) -> UUID | int | str | datetime:
    if not isinstance(value, str):
        raise InvalidCursorError
    try:
        if kind == "uuid":
            return UUID(value)
        if kind == "int":
            parsed = int(value)
            if str(parsed) != value:
                raise InvalidCursorError
            return parsed
        if kind == "datetime":
            parsed_at = datetime.fromisoformat(value)
            if parsed_at.tzinfo is None or parsed_at.utcoffset() is None:
                raise InvalidCursorError
            return parsed_at
    except (ValueError, OverflowError) as error:
        raise InvalidCursorError from error
    return value


def _encode_cursor[T](keyset: Keyset[T], context: Mapping[str, CursorScalar], item: T) -> CursorToken:
    payload = {
        "a": [_serialize_anchor(getattr(item, column.column.key), column.kind) for column in keyset.columns],
        "n": keyset.namespace,
        "q": _context_fingerprint(context),
        "v": CURSOR_VERSION,
    }
    token = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    if len(token) > MAX_CURSOR_LENGTH:
        raise InvalidCursorError
    return token


def _decode_cursor[T](token: str, keyset: Keyset[T], context: Mapping[str, CursorScalar]) -> tuple[UUID | int | str | datetime, ...]:
    if len(token) > MAX_CURSOR_LENGTH:
        raise InvalidCursorError
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"v", "n", "q", "a"}:
            raise InvalidCursorError
        if payload["v"] != CURSOR_VERSION or payload["n"] != keyset.namespace or payload["q"] != _context_fingerprint(context):
            raise InvalidCursorError
        anchors = payload["a"]
        if not isinstance(anchors, list) or len(anchors) != len(keyset.columns):
            raise InvalidCursorError
        return tuple(_parse_anchor(anchor, column.kind) for anchor, column in zip(anchors, keyset.columns, strict=True))
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError, TypeError, KeyError) as error:
        raise InvalidCursorError from error


def _after[T](keyset: Keyset[T], anchors: tuple[UUID | int | str | datetime, ...]) -> ColumnElement[bool]:
    branches: list[ColumnElement[bool]] = []
    for index, key_column in enumerate(keyset.columns):
        prefix = [previous.column == anchors[position] for position, previous in enumerate(keyset.columns[:index])]
        comparison = key_column.column > anchors[index] if key_column.direction == "asc" else key_column.column < anchors[index]
        branches.append(and_(*prefix, comparison))
    return or_(*branches)


async def keyset_page[T](
    statement: Select[tuple[T]],
    request: PageQuery,
    keyset: Keyset[T],
    *,
    cursor_context: Mapping[str, CursorScalar] | None = None,
) -> PageSlice[T]:
    context = cursor_context or {}
    if request.cursor is not None:
        statement = statement.where(_after(keyset, _decode_cursor(request.cursor, keyset, context)))
    ordering = [column.column.asc() if column.direction == "asc" else column.column.desc() for column in keyset.columns]
    items = tuple((await current_session().execute(statement.order_by(*ordering).limit(request.limit + 1))).scalars().all())
    visible = items[: request.limit]
    next_cursor = _encode_cursor(keyset, context, visible[-1]) if len(items) > request.limit else None
    return PageSlice(items=visible, next_cursor=next_cursor)
